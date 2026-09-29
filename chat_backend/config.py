from pydantic import Field
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

    # Session lifetime (gaps S7/S9, Q5/Q9): the access token stays short and
    # stateless; the rotating refresh token is the revocable half and therefore
    # the one that sets the session's outer bound — 14 days of a browser that
    # never refreshes, renewed on every refresh (sliding expiry).
    refresh_token_expire_days: int = Field(default=14, gt=0)
    # `Secure` would make a browser drop the cookie over plain HTTP, so it is a
    # switch rather than a constant: flip it in any deployment that terminates
    # TLS (Q5). `HttpOnly` and `SameSite=Strict` are unconditional (S9).
    refresh_cookie_secure: bool = False

    # Connection pool (gap D9): env-overridable so a hosted deployment can tune
    # to its pooler's limit without a code change.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Credential rate limits (gap S6): attempts per client address, per window,
    # on the two endpoints that mint or create an identity. Login is the
    # brute-force surface, so its window is short; registration is the spam
    # surface, so its budget is smaller and its window longer. Tuned by env so
    # an operator can tighten either without a code change (as with the pool).
    # `ge=1`/`gt=0`: a zero limit would refuse even the first attempt and a
    # non-positive window is meaningless, so a bad value stops the app at
    # startup instead of surfacing as a 500 on someone's first login.
    login_rate_limit: int = Field(default=10, ge=1)
    login_rate_window_seconds: float = Field(default=300.0, gt=0)
    register_rate_limit: int = Field(default=5, ge=1)
    register_rate_window_seconds: float = Field(default=3600.0, gt=0)

    # NLP models (gaps A1, A7): the summariser is the small distilled model, and
    # both are pinned to an exact upstream revision so the same input keeps
    # producing the same output after an upstream update. Set a revision to ""
    # to follow the model's main branch instead.
    ai_sentiment_model: str = "distilbert-base-uncased-finetuned-sst-2-english"
    ai_sentiment_revision: str = "714eb0fa89d2f80546fda750413ed43d93601a13"
    ai_summary_model: str = "sshleifer/distilbart-cnn-6-6"
    ai_summary_revision: str = "d2fde4ca965ba893255479612e4b801aa6500029"


settings = Settings()