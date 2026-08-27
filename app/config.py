from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./uptime.db"
    slack_webhook_url: str = ""

    failure_threshold: int = 3
    scheduler_tick_seconds: int = 5
    default_interval_seconds: int = 60
    default_timeout_seconds: int = 10

    # How many checks run in parallel. Checks are network-bound, so a slow
    # endpoint would otherwise delay every monitor queued behind it.
    check_concurrency: int = 8

    # "json" emits one object per line for log aggregators; "text" is readable
    # in a terminal.
    log_format: str = "text"
    log_level: str = "INFO"

    # Rolling window used for the /metrics endpoint and dashboard percentiles.
    metrics_window_hours: int = 24

    # Run the poller inside the web process instead of as its own service.
    # Needed on hosts whose free tier offers no worker process type; two
    # processes remains the default and the better shape.
    run_scheduler_in_web: bool = False

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
