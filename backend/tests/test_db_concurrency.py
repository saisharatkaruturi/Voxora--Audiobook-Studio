"""SQLite concurrency: background read-then-write units of work must wait for the
write lock instead of failing with "database is locked"."""

import threading

from sqlalchemy import select, update

from app.db.session import session_scope
from app.models import User


def test_concurrent_read_then_write_never_locks(client, user):
    with session_scope() as db:
        uid = db.scalar(select(User.id).limit(1))
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def worker(n: int) -> None:
        start.wait()
        try:
            for i in range(25):
                # The JobContext.check() shape: read first, then write.
                with session_scope() as db:
                    db.scalar(select(User.display_name).where(User.id == uid))
                    db.execute(update(User).where(User.id == uid).values(display_name=f"w{n}-{i}"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[0]


def test_concurrent_writes_to_the_same_storage_key(tmp_path):
    """Two chapters caching an identical line write the same key at the same time."""
    from app.providers.storage.local import LocalStorage

    tmp_path = tmp_path.resolve()
    storage = LocalStorage(tmp_path)
    errors: list[BaseException] = []
    start = threading.Barrier(12)

    def worker() -> None:
        start.wait()
        try:
            for _ in range(20):
                storage.save_bytes("cache/tts/ab/same.flac", b"x" * 50_000)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[0]
    assert (tmp_path / "cache/tts/ab/same.flac").read_bytes() == b"x" * 50_000
    assert not list(tmp_path.rglob("*.part"))


def test_many_synthesis_threads_share_the_database(client, user):
    """The per-chunk pattern at book scale: 150 threads read the segment cache and
    write a row concurrently. Nobody may starve on the write lock or the pool."""
    from app.db.session import best_effort_write

    with session_scope() as db:
        uid = db.scalar(select(User.id).limit(1))
    errors: list[BaseException] = []
    skipped: list[bool] = []
    start = threading.Barrier(150)

    def chunk(n: int) -> None:
        start.wait()
        try:
            for i in range(4):
                with session_scope(write=False) as db:
                    db.scalar(select(User.display_name).where(User.id == uid))
                ok = best_effort_write(lambda db: db.execute(update(User).where(User.id == uid).values(display_name=f"c{n}-{i}")))
                if not ok:
                    skipped.append(True)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=chunk, args=(n,)) for n in range(150)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[0]
    assert not skipped
