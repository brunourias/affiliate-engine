from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]
class Settings(BaseSettings):
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'affiliate_engine.db').as_posix()}"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    log_level: str = "INFO"
    scheduler_interval_seconds: int = 30
    meli_site_id: str = Field(default="MLB", validation_alias="MELI_SITE_ID")
    meli_client_id: str = Field(default="", validation_alias="MELI_CLIENT_ID")
    meli_client_secret: str = Field(default="", validation_alias="MELI_CLIENT_SECRET")
    meli_access_token: str = Field(default="", validation_alias="MELI_ACCESS_TOKEN")
    model_config = SettingsConfigDict(env_prefix="AFFILIATE_", env_file=".env", extra="ignore")
    @property
    def cors_origin_list(self): return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
settings = Settings()
