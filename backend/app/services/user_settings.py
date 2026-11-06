"""Per-user preferences (default narration, playback, privacy)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserSettings

PREFERENCE_DEFAULTS = {
    "default_provider": None,
    "default_voices": {},  # {"en": {"provider": "piper", "voice_id": "..."}}
    "default_speed": 1.0,
    "playback_rate": 1.0,
    "skip_back_seconds": 15,
    "skip_forward_seconds": 30,
    "narration_cleanup": True,
    "auto_analyze": True,
    "build_full_audiobook": False,  # downloads join chapters on demand; no second copy
    "audio_format": None,
    "audio_bitrate": None,
    "analytics_opt_in": False,
    "confirm_cloud_processing": True,
}


def get_preferences(db: Session, user_id: str) -> dict:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    return {**PREFERENCE_DEFAULTS, **(row.preferences if row else {})}


def update_preferences(db: Session, user_id: str, changes: dict) -> dict:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    if row is None:
        row = UserSettings(user_id=user_id, preferences={})
        db.add(row)
    merged = {**(row.preferences or {}), **{k: v for k, v in changes.items() if k in PREFERENCE_DEFAULTS}}
    row.preferences = merged
    db.commit()
    return {**PREFERENCE_DEFAULTS, **merged}


def default_narration_for(db: Session, user_id: str, language: str | None) -> dict:
    prefs = get_preferences(db, user_id)
    voice = (prefs.get("default_voices") or {}).get(language or "en") or {}
    narration = {
        "speed": prefs.get("default_speed", 1.0),
        "narration_cleanup": prefs.get("narration_cleanup", True),
        "build_full_audiobook": prefs.get("build_full_audiobook", True),
    }
    if voice.get("voice_id"):
        narration["provider"] = voice.get("provider")
        narration["voice_id"] = voice["voice_id"]
    elif prefs.get("default_provider"):
        narration["provider"] = prefs["default_provider"]
    if prefs.get("audio_format"):
        narration["format"] = prefs["audio_format"]
    if prefs.get("audio_bitrate"):
        narration["bitrate"] = prefs["audio_bitrate"]
    from app.services.narration_settings import resolve

    resolved = resolve(narration, language)
    return {k: resolved[k] for k in ("provider", "voice_id")} | narration
