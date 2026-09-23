from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment / `.env`.

    `SECRET_KEY` and `DATABASE_URL` have no defaults on purpose: the app must
    fail at startup rather than run with fallback credentials (gap S5).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 30
    debug: bool = False


settings = Settings()