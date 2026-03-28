import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ADMIN_SECRET_KEY: str = "dev-admin-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

    # Max activations per plan
    MAX_ACTIVATIONS_TRIAL: int = 1
    MAX_ACTIVATIONS_BASIC: int = 2
    MAX_ACTIVATIONS_PRO: int = 5

    # Trial duration in days
    TRIAL_DURATION_DAYS: int = 30

    # Grace period thresholds (days after trial/paid expiry)
    GRACE_PERIOD_DAYS: int = 7       # grace: 1-7 days after expiry
    DEGRADED_PERIOD_DAYS: int = 14   # degraded: 8-14 days after expiry
    # 15+ days → blocked (only cash sales)

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
