from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MEDIAMTX_API_URL: str = os.environ.get("MEDIAMTX_API_URL","http://mediamtx:9997")
    MEDIAMTX_PUBLIC_HOST: str = os.environ.get("MEDIAMTX_PUBLIC_HOST", "")
    USE_MOCK: bool = bool(os.environ.get("USE_MOCK", False))
    API_HOST: str = os.environ.get("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.environ.get("API_PORT", 8000))
    LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "/var/log/mediamtx.log")
    NODE_EXPORTER_URL: str = os.environ.get("NODE_EXPORTER_URL", "http://127.0.0.1:9100")
    MEDIAMTX_CONFIG_PATH: str = os.environ.get("MEDIAMTX_CONFIG_PATH", "mediamtx.yml")

    # --- JWT Authentication ---

    AUTH_USERNAME: str = os.environ.get("AUTH_USERNAME", "admin")
    AUTH_PASSWORD: str = os.environ.get("AUTH_PASSWORD", "admin")
    JWT_SECRET: str = os.environ.get("JWT_SECRET", "")
    JWT_EXPIRE_MINUTES: int = int(os.environ.get("JWT_EXPIRE_MINUTES", 480))
    JWT_SECURE_COOKIE: bool = bool(os.environ.get("JWT_SECURE_COOKIE", False))


settings = Settings()
