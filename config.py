from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MEDIAMTX_API_URL: str = "http://mediamtx:9997"
    USE_MOCK: bool = False
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_FILE_PATH: str = "/var/log/mediamtx.log"
    NODE_EXPORTER_URL: str = "http://127.0.0.1:9100"

    # --- JWT Authentication ---

    AUTH_USERNAME: str = "admin"
    AUTH_PASSWORD: str = "admin"
    JWT_SECRET: str = ""
    JWT_EXPIRE_MINUTES: int = 480
    JWT_SECURE_COOKIE: bool = False


settings = Settings()
