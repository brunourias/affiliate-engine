from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]
class Settings(BaseSettings):
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'affiliate_engine.db').as_posix()}"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    log_level: str = "INFO"
    scheduler_interval_seconds: int = 30
    model_config = SettingsConfigDict(env_prefix="AFFILIATE_", env_file=".env", extra="ignore")
    @property
    def cors_origin_list(self): return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
settings = Settings()
