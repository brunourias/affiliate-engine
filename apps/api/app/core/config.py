from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]
class Settings(BaseSettings):
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'affiliate_engine.db').as_posix()}"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    log_level: str = "INFO"
    scheduler_interval_seconds: int = 30
    media_root: str = str(ROOT / "data" / "media")
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    tts_provider: str = ""
    tts_invocation_mode: str = "CLI"
    tts_python_path: str = ""
    tts_python_module: str = "piper"
    tts_executable_path: str = Field(default="", validation_alias=AliasChoices("AFFILIATE_TTS_EXECUTABLE_PATH","PIPER_EXECUTABLE_PATH"))
    tts_model_bruno: str = Field(default="", validation_alias=AliasChoices("AFFILIATE_TTS_MODEL_BRUNO","BRUNO_MODEL_PATH"))
    tts_model_carol: str = Field(default="", validation_alias=AliasChoices("AFFILIATE_TTS_MODEL_CAROL","CAROL_MODEL_PATH"))
    tts_model_narrator: str = Field(default="", validation_alias=AliasChoices("AFFILIATE_TTS_MODEL_NARRATOR","NARRATOR_MODEL_PATH"))
    tts_model_config_bruno: str = ""
    tts_model_config_carol: str = ""
    tts_model_config_narrator: str = ""
    media_asset_max_bytes: int = 10 * 1024 * 1024
    media_pipeline_mode: str = "LOCAL"
    media_audio_padding_seconds: float = 0.6
    media_subprocess_timeout_seconds: int = 180
    media_font_name: str = "Arial"
    media_background_color: str = "#102B32"
    media_accent_color: str = "#59C4C0"
    media_text_color: str = "#FFFFFF"
    media_safe_margin_ratio: float = 0.08
    meli_site_id: str = Field(default="MLB", validation_alias="MELI_SITE_ID")
    meli_client_id: str = Field(default="", validation_alias="MELI_CLIENT_ID")
    meli_client_secret: str = Field(default="", validation_alias="MELI_CLIENT_SECRET")
    meli_access_token: str = Field(default="", validation_alias="MELI_ACCESS_TOKEN")
    model_config = SettingsConfigDict(env_prefix="AFFILIATE_", env_file=".env", extra="ignore")
    @property
    def cors_origin_list(self): return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
settings = Settings()
