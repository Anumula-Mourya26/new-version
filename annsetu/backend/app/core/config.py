from functools import lru_cache
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "AnnSetu"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    APP_ENV: str = "development"

    # Database: defaults to SQLite for zero-config local run, supports Postgres in production
    DATABASE_URL: str = "sqlite+aiosqlite:///./annsetu.db"

    # Security
    JWT_SECRET_KEY: str = "annsetu-secret-key-for-sih26032-msp-queue-2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # OTP simulation for testing & demo
    OTP_MOCK_ENABLED: bool = True
    OTP_MOCK_CODE: str = "1234"
    OTP_EXPIRY_SECONDS: int = 300

    # CORS
    CORS_ORIGINS: Union[str, List[str]] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, list):
            return v
        return ["*"]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
