from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_organization: str | None = None
    app_database_path: str = str(BASE_DIR / "backend" / "data" / "app.sqlite3")
    cookie_secure: bool = False
    max_result_rows: int = Field(default=200, ge=1, le=5000)
    admin_email: str | None = "rajputprateeksingh075@gmail.com"
    admin_password: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    app_public_url: str = "http://localhost:5173"

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
