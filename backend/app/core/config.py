from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str = (
        "postgresql://sqlcopilot:change_me_to_a_local_dev_password"
        "@localhost:5432/sqlcopilot"
    )
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_organization: str | None = None
    app_database_path: str = str(BASE_DIR / "backend" / "data" / "app.sqlite3")
    credential_encryption_key: str | None = None
    cookie_secure: bool = False
    allow_private_database_hosts: bool = False
    statement_timeout_ms: int = 5000
    max_result_rows: int = 200

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
