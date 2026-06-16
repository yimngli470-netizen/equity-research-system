from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://researcher:changeme_local_dev@db:5432/equity_research"
    redis_url: str = "redis://redis:6379/0"
    anthropic_api_key: str = ""
    news_api_key: str = ""
    fmp_api_key: str = ""
    env: str = "development"
    log_level: str = "INFO"

    # LLM model selection — TWO tiers, set in ONE place (override per-env via OPUS_MODEL / SONNET_MODEL
    # in .env, no code change). Anthropic retires dated snapshots periodically (a retired id returns
    # 404 not_found_error and every agent fails), so keep these current — see the latest ids in
    # CLAUDE.md / the claude-api skill. opus = deep analysis (agents, judge, forecast); sonnet = fast
    # tasks (news, summaries, archetype, KPI, IR repair, grading).
    opus_model: str = "claude-opus-4-8"
    sonnet_model: str = "claude-sonnet-4-6"

    # Sync database URL for Alembic (replaces asyncpg with psycopg2)
    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
