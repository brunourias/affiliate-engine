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
    public_media_base_url: str = Field(default="", validation_alias=AliasChoices("AFFILIATE_PUBLIC_MEDIA_BASE_URL","PUBLIC_MEDIA_BASE_URL"))
    public_media_signing_secret: str = Field(default="", validation_alias=AliasChoices("AFFILIATE_PUBLIC_MEDIA_SIGNING_SECRET","PUBLIC_MEDIA_SIGNING_SECRET"))
    public_media_ttl_minutes: int = Field(default=60, validation_alias=AliasChoices("AFFILIATE_PUBLIC_MEDIA_TTL_MINUTES","PUBLIC_MEDIA_TTL_MINUTES"))
    instagram_client_id: str = ""
    instagram_client_secret: str = ""
    instagram_redirect_uri: str = ""
    instagram_api_version: str = "v24.0"
    instagram_oauth_timeout_seconds: int = 15
    instagram_oauth_state_ttl_minutes: int = 10
    instagram_token_expiring_soon_days: int = 7
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
    tts_pronunciation_overrides: dict[str, str] = Field(default_factory=dict)
    chatterbox_python_path: str = ""
    chatterbox_language: str = "pt"
    chatterbox_exaggeration_bruno: float = 0.60
    chatterbox_cfg_weight_bruno: float = 0.40
    chatterbox_exaggeration_carol: float = 0.60
    chatterbox_cfg_weight_carol: float = 0.40
    chatterbox_exaggeration_narrator: float = 0.50
    chatterbox_cfg_weight_narrator: float = 0.45
    chatterbox_reference_bruno: str = ""
    chatterbox_reference_carol: str = ""
    chatterbox_reference_narrator: str = ""
    chatterbox_model_load_timeout_seconds: int = 300
    chatterbox_synthesis_timeout_seconds: int = 180
    chatterbox_diagnostic_timeout_seconds: int = 90
    chatterbox_trim_silence_enabled: bool = True
    chatterbox_trim_silence_threshold_db: float = -50.0
    chatterbox_trim_silence_duration_seconds: float = 0.15
    chatterbox_trim_silence_padding_seconds: float = 0.10
    subtitle_lead_in_seconds: float = 0.05
    media_asset_max_bytes: int = 10 * 1024 * 1024
    media_pipeline_mode: str = "LOCAL"
    media_audio_padding_seconds: float = 0.6
    media_timeline_drift_tolerance_seconds: float = 0.25
    media_motion_zoom_percent: float = 0.05
    media_motion_avatar_float_pixels: int = 12
    media_motion_enter_duration_ms: int = 220
    media_motion_exit_duration_ms: int = 180
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
