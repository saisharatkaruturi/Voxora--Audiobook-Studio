"""Housekeeping: temp files, orphaned cache segments."""

from __future__ import annotations

import time

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def cleanup_temp_files() -> int:
    from app.services.generation import tmp_dir

    settings = get_settings()
    ttl = settings.temp_file_ttl_hours * 3600
    now = time.time()
    removed = 0
    roots = [tmp_dir()]
    if settings.storage_provider == "s3":
        # Downloaded copies of cloud objects (for ffmpeg, exports): scratch only.
        roots.append(settings.storage_path / "_s3cache")
    paths = [p for root in roots if root.exists() for p in root.rglob("*")]
    for path in sorted(paths, reverse=True):
        try:
            if now - path.stat().st_mtime < ttl:
                continue
            if path.is_file():
                path.unlink()
                removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            continue
    if removed:
        log.info("maintenance.temp_cleaned", files=removed)
    from app.services.handoff import device_mode, sweep_undelivered

    if device_mode():
        from app.db.session import session_scope

        with session_scope() as db:
            sweep_undelivered(db)
    return removed


def clear_tts_cache() -> dict:
    """Delete cached TTS segments (they're regenerated on demand)."""
    from sqlalchemy import delete, func, select

    from app.db.session import session_scope
    from app.models import AudioAsset
    from app.providers.storage import get_storage

    with session_scope() as db:
        count, size = db.execute(select(func.count(), func.coalesce(func.sum(AudioAsset.size_bytes), 0)).where(AudioAsset.kind == "segment")).one()
        db.execute(delete(AudioAsset).where(AudioAsset.kind == "segment"))
    get_storage().delete_prefix("cache/tts")
    return {"segments": int(count), "bytes": int(size)}
