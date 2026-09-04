from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Validated application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="GOVINSIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    postgres_db: str = "govinsight"
    postgres_user: str = "govinsight_app"
    postgres_password: SecretStr = SecretStr("govinsight_local")
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_pool_size: int = Field(default=5, gt=0)
    postgres_max_overflow: int = Field(default=10, ge=0)
    postgres_pool_recycle_seconds: int = Field(default=300, gt=0)
    database_dsn: SecretStr | None = None
    agent_provider: Literal["rules", "openai"] = "rules"
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_timeout_seconds: float = Field(default=12.0, gt=0)
    agent_fallback_enabled: bool = True
    pncp_base_url: AnyHttpUrl = AnyHttpUrl("https://pncp.gov.br/api/consulta")
    pncp_timeout_seconds: float = Field(default=30.0, gt=0)
    pncp_retry_max_attempts: int = Field(default=4, gt=0)
    pncp_retry_base_delay_seconds: float = Field(default=0.5, gt=0)
    pncp_retry_max_delay_seconds: float = Field(default=8.0, gt=0)

    @property
    def database_url(self) -> str:
        if self.database_dsn is not None:
            return self.database_dsn.get_secret_value()
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @model_validator(mode="after")
    def validate_openai_configuration(self) -> "Settings":
        if self.agent_provider == "openai" and (
            self.openai_api_key is None or not self.openai_model
        ):
            raise ValueError("OpenAI provider requires API key and model")
        if self.app_env == "production":
            if self.database_dsn is None:
                raise ValueError("production requires a managed database DSN")
            dsn = self.database_dsn.get_secret_value().lower()
            if "sslmode=require" not in dsn and "sslmode=verify-full" not in dsn:
                raise ValueError("production database DSN must require SSL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
