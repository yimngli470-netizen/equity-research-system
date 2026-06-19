import os
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# Per-env, NON-secret config lives in backend/config/<app_env>.yaml (committed). Secrets
# (ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN) stay in .env / env vars, never in the YAML.
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://researcher:changeme_local_dev@db:5432/equity_research"
    redis_url: str = "redis://redis:6379/0"
    anthropic_api_key: str = ""
    news_api_key: str = ""
    fmp_api_key: str = ""
    env: str = "development"
    log_level: str = "INFO"

    # ── Environment & LLM backend ────────────────────────────────────────────────────────────────
    # app_env selects which config/<app_env>.yaml is layered in: "dev" (local docker, DEFAULT) or
    # "prod" (servers — MUST set APP_ENV=prod). The two envs differ in how they reach Claude:
    #   llm_backend="api"         → Anthropic SDK billed to ANTHROPIC_API_KEY (prod).
    #   llm_backend="claude_code" → route every completion through the `claude` CLI using
    #                               CLAUDE_CODE_OAUTH_TOKEN, billed to your Max/Pro SUBSCRIPTION
    #                               (dev only; shares your 5-hour interactive rate limits).
    # Both are read through the single factory in app/llm/client.py — see make_llm_client().
    app_env: str = "dev"
    llm_backend: str = "api"
    claude_code_oauth_token: str = ""

    # LLM model selection — TWO tiers, set in ONE place (override per-env via OPUS_MODEL / SONNET_MODEL
    # in .env, no code change). Anthropic retires dated snapshots periodically (a retired id returns
    # 404 not_found_error and every agent fails), so keep these current — see the latest ids in
    # CLAUDE.md / the claude-api skill. opus = deep analysis (agents, judge, forecast); sonnet = fast
    # tasks (news, summaries, archetype, KPI, IR repair, grading).
    opus_model: str = "claude-opus-4-8"
    sonnet_model: str = "claude-sonnet-4-6"

    @property
    def llm_configured(self) -> bool:
        """Whether the ACTIVE backend has the credential it needs. Use this to gate optional LLM
        steps — not `anthropic_api_key`, which is empty in dev (the subscription path uses
        CLAUDE_CODE_OAUTH_TOKEN instead, so an api-key check would wrongly skip every LLM call)."""
        if self.llm_backend == "claude_code":
            return bool(self.claude_code_oauth_token)
        return bool(self.anthropic_api_key)

    # Sync database URL for Alembic (replaces asyncpg with psycopg2)
    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Layer config/<APP_ENV>.yaml in BELOW env vars (so env/.env still override). The YAML file
        is picked from the APP_ENV env var directly (read before the model is built)."""
        env_name = os.environ.get("APP_ENV", cls.model_fields["app_env"].default)
        yaml_file = _CONFIG_DIR / f"{env_name}.yaml"
        sources = [init_settings, env_settings, dotenv_settings]
        if yaml_file.is_file():
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=yaml_file))
        sources.append(file_secret_settings)
        return tuple(sources)


settings = Settings()
