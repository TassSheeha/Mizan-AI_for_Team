"""
app.core.config — Central backend settings loaded from environment / .env.

The Groq key and model are inherited from the project root .env so the
Streamlit app and the API share the exact same AI configuration.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── AI provider (unchanged models — Groq + llama-3.3-70b-versatile) ────
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ─── Security ────────────────────────────────────────────────────────────
    JWT_SECRET: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # ─── Bootstrap admin ─────────────────────────────────────────────────────
    ADMIN_EMAIL: str = "admin@mizan.ly"
    ADMIN_PASSWORD: str = "Mizan@Admin2026"

    # ─── Server ──────────────────────────────────────────────────────────────
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # ─── Database ────────────────────────────────────────────────────────────
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'backend' / 'mizan.db'}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
