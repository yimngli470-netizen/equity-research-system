from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://researcher:changeme_local_dev@db:5432/equity_research"
    redis_url: str = "redis://redis:6379/0"
    anthropic_api_key: str = ""
    news_api_key: str = ""
    env: str = "development"
    log_level: str = "INFO"

    # Sync database URL for Alembic (replaces asyncpg with psycopg2)
    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
