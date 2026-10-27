from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings (BaseSettings):
    database_url: str
    secret_key: str
    clinic_tz:str = "Africa/Nairobi"
    slot_minutes: int = 30
    booking_lead_minutes: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def fix_db_url(cls, db: str) -> str:
        if db.startswith("postgres://"):
            return db.replace("postgres://", "postgresql+asyncpg://", 1)
        return db

settings = Settings()
