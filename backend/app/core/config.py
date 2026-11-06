"""Application configuration.

All settings come from environment variables (or a `.env` file in the backend
directory). Nothing vendor-specific is hardcoded elsewhere: providers are chosen
by name here and resolved through the provider registries.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App -----------------------------------------------------------------
    app_name: str = "VOXORA"
    environment: Literal["development", "production", "test"] = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    public_base_url: str = "http://127.0.0.1:8000"

    # --- Security ------------------------------------------------------------
    secret_key: str | None = None  # auto-generated and persisted when unset
    access_token_ttl_minutes: int = 60 * 24 * 14
    media_url_ttl_seconds: int = 60 * 60 * 6
    allow_registration: bool = True
    rate_limit_enabled: bool = True
    # Uploads per user per hour (high enough to import a whole bookshelf at once)
    upload_rate_limit_per_hour: int = 120

    # --- Accounts (Supabase Auth) ---------------------------------------------------
    # auto = Supabase when SUPABASE_URL is set, else built-in email/password accounts.
    auth_provider: Literal["auto", "local", "supabase"] = "auto"
    supabase_url: str | None = None  # https://<project-ref>.supabase.co
    # Public (anon / publishable) key, handed to the browser so it can talk to Supabase Auth.
    supabase_anon_key: str | None = None
    # Only for projects still on the legacy HS256 JWT secret; asymmetric signing keys
    # (the default for new projects) are verified through the project's public JWKS.
    supabase_jwt_secret: str | None = None
    supabase_jwt_audience: str = "authenticated"
    # These emails become admins (there is no "first account is admin" with Supabase).
    admin_emails: Annotated[list[str], NoDecode] = []
    # Social sign-in buttons to show; each must be enabled in Supabase -> Authentication -> Providers.
    supabase_oauth_providers: Annotated[list[str], NoDecode] = ["google"]

    # --- Storage & database ----------------------------------------------------
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'studio.db').as_posix()}"
    storage_provider: Literal["local", "s3"] = "local"
    storage_path: Path = BACKEND_DIR / "data" / "storage"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    max_file_size_mb: int = 300
    max_pages: int = 5000
    min_free_disk_mb: int = 500

    # --- Workers -----------------------------------------------------------------
    run_worker_in_process: bool = True
    worker_concurrency: int = 4
    # Extra workers for background jobs (search index, cast, insights, exports); 0 = shared lane
    background_workers: int = 1
    worker_poll_interval: float = 1.0
    job_heartbeat_timeout: int = 120
    job_max_attempts: int = 3

    # --- OCR ---------------------------------------------------------------------
    ocr_provider: str = "auto"  # auto | tesseract | rapidocr | easyocr
    tesseract_cmd: str | None = None
    ocr_dpi: int = 300
    # Small servers (e.g. 512 MB): one OCR thread and no memory arena, trading speed for RAM.
    ocr_low_memory: bool = False
    ocr_low_confidence_threshold: float = 0.70

    # --- TTS ---------------------------------------------------------------------
    tts_provider: str = "piper"  # piper | sapi | edge | openai | elevenlabs
    tts_enabled_providers: Annotated[list[str], NoDecode] = ["piper", "sapi", "edge", "openai", "elevenlabs"]
    piper_voices_path: Path = BACKEND_DIR / "data" / "voices" / "piper"
    piper_default_voice: str = "en_US-lessac-medium"
    tts_api_key: str | None = None  # generic fallback key for cloud TTS
    openai_tts_api_key: str | None = None
    openai_tts_base_url: str = "https://api.openai.com/v1"
    openai_tts_model: str = "gpt-4o-mini-tts"
    elevenlabs_api_key: str | None = None
    elevenlabs_model: str = "eleven_multilingual_v2"
    tts_timeout_seconds: int = 120
    tts_max_retries: int = 5
    # 0 = automatic: chapters generated at once (cloud voices use several)
    chapter_concurrency: int = 0
    # Scanned pages OCR'd at once (each with its own engine)
    ocr_parallel_pages: int = 1
    # Keep synthesized pieces to speed up re-narration after edits (costs storage)
    tts_segment_cache: bool = True
    tts_concurrency: int = 0  # parallel TTS chunks; 0 = automatic (hardware / provider aware)
    encode_concurrency: int = 0  # chapters encoded side by side; 0 = automatic (2-4)
    piper_sessions: int = 0  # parallel Piper sessions per voice; 0 = cores // 2 (max 6), 2 with CUDA

    # --- Audio -------------------------------------------------------------------
    ffmpeg_path: str | None = None
    audio_sample_rate: int = 24000
    audio_default_format: Literal["mp3", "m4a", "wav"] = "mp3"
    audio_default_bitrate: str = "96k"
    audio_target_lufs: float = -18.0

    # --- LLM / embeddings ----------------------------------------------------------
    llm_provider: str = "auto"  # auto | none | gemini | ollama | openai | anthropic  (auto: Gemini if GEMINI_API_KEY, else Claude if Anthropic credentials, else local Ollama)
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "auto"  # auto = best installed local chat model
    openai_llm_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-opus-5"
    gemini_api_key: str | None = None
    gemini_model: str = "auto"  # auto = newest stable Flash model on the account
    llm_timeout_seconds: int = 600

    embedding_provider: str = "fastembed"  # hashing | fastembed | ollama | openai
    embedding_model: str | None = None  # overrides both defaults below
    embedding_model_en: str = "BAAI/bge-base-en-v1.5"
    embedding_model_multilingual: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    rerank_enabled: bool = True  # cross-encoder reranking of retrieved passages
    rerank_model_en: str = "jinaai/jina-reranker-v1-turbo-en"
    rerank_model_multilingual: str = "jinaai/jina-reranker-v2-base-multilingual"
    fastembed_cache_path: Path = BACKEND_DIR / "data" / "models"

    # --- Privacy -----------------------------------------------------------------
    analytics_enabled: bool = False
    temp_file_ttl_hours: int = 2  # leftovers from interrupted chapters; a chapter takes minutes
    # device = finished audio is handed to the listener's browser and then deleted here:
    # the server converts books but keeps no audio. server = audio stays in storage.
    audio_delivery: Literal["server", "device"] = "server"
    # In device mode, chapter audio nobody collected is deleted after this many hours.
    device_handoff_ttl_hours: int = 24

    @field_validator("cors_origins", "tts_enabled_providers", "admin_emails", "supabase_oauth_providers", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            if v.strip().startswith("["):
                import json

                return json.loads(v)
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def uses_supabase_auth(self) -> bool:
        if self.auth_provider == "auto":
            return bool(self.supabase_url)
        return self.auth_provider == "supabase"

    def is_admin_email(self, email: str | None) -> bool:
        return (email or "").strip().lower() in {e.strip().lower() for e in self.admin_emails if e.strip()}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _load_or_create_secret(path: Path) -> str:
    """Persist a generated secret so tokens and signed URLs survive restarts and
    are shared between the API and worker processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        settings.secret_key = _load_or_create_secret(BACKEND_DIR / "data" / ".secret_key")
    if settings.supabase_url:
        settings.supabase_url = settings.supabase_url.rstrip("/")
    # Accept Postgres links exactly as Supabase / Render / Heroku print them.
    for prefix in ("postgresql://", "postgres://"):
        if settings.database_url.startswith(prefix):
            settings.database_url = "postgresql+psycopg://" + settings.database_url[len(prefix):]
    if settings.audio_delivery == "device":
        # No audio may stay on the server: no reusable synthesized pieces either.
        settings.tts_segment_cache = False
    if settings.uses_supabase_auth and not settings.supabase_url:
        raise RuntimeError("AUTH_PROVIDER=supabase needs SUPABASE_URL (https://<project-ref>.supabase.co).")
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    if settings.is_sqlite:
        db_file = settings.database_url.split("sqlite:///", 1)[-1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    return settings
