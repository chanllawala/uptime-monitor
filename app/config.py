from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./uptime.db"
    slack_webhook_url: str = ""

    failure_threshold: int = 3
    scheduler_tick_seconds: int = 5
    default_interval_seconds: int = 60
    default_timeout_seconds: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Managed Postgres providers hand out "postgres://" URLs, a scheme
        # SQLAlchemy 2.x no longer recognises.
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql://", 1)
        return value

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_webhook_url.strip())


settings = Settings()
