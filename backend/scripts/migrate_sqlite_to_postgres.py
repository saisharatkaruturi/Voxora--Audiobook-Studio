"""Copy a VOXORA SQLite database into PostgreSQL (e.g. Supabase Postgres).

    python scripts/migrate_sqlite_to_postgres.py --target "postgresql+psycopg://postgres.<ref>:<pw>@<host>:5432/postgres"
    python scripts/migrate_sqlite_to_postgres.py --source sqlite:///./data/studio.db --target ... [--dry-run]

Creates the schema on the target, then copies every table in foreign-key order.
Refuses to write into a target that already holds VOXORA rows. The source is only
read. Audio and uploaded files are not in the database: they stay wherever
STORAGE_PATH / S3 points, so keep that setting the same after switching.

Use Supabase's *session* connection (port 5432) or the direct connection for this
bulk copy; the transaction pooler (6543) works too but is slower.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, inspect, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  (register models)

BATCH = 500


def _clean(value):
    # PostgreSQL text can't hold NUL characters; SQLite happily stores them (OCR noise).
    if isinstance(value, str) and "\x00" in value:
        return value.replace("\x00", "")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help="SQLite URL (default: DATABASE_URL from settings if it is SQLite)")
    ap.add_argument("--target", required=True, help="postgresql+psycopg://... URL")
    ap.add_argument("--dry-run", action="store_true", help="count rows only; write nothing")
    args = ap.parse_args()

    source_url = args.source or get_settings().database_url
    if not source_url.startswith("sqlite"):
        print("The source must be a SQLite database (pass --source sqlite:///path/to/studio.db).")
        return 2
    if not args.target.startswith("postgresql"):
        print("The target must be a PostgreSQL URL (postgresql+psycopg://...).")
        return 2

    src = create_engine(source_url)
    dst = create_engine(args.target, connect_args={"prepare_threshold": None} if "+psycopg" in args.target else {})
    src_tables = set(inspect(src).get_table_names())

    if not args.dry_run:
        Base.metadata.create_all(dst)
        with dst.connect() as conn:
            busy = [t.name for t in Base.metadata.sorted_tables if conn.scalar(select(func.count()).select_from(t))]
        if busy:
            print(f"The target already has data in: {', '.join(busy)}. Use an empty database.")
            return 1

    total = 0
    for table in Base.metadata.sorted_tables:
        if table.name not in src_tables:
            print(f"  {table.name:<24} (not in source, skipped)")
            continue
        have = {c["name"] for c in inspect(src).get_columns(table.name)}
        cols = [c for c in table.columns if c.name in have]
        with src.connect() as sconn:
            count = sconn.scalar(select(func.count()).select_from(table)) or 0
            print(f"  {table.name:<24} {count:>8} rows")
            total += count
            if args.dry_run or not count:
                continue
            result = sconn.execution_options(stream_results=True).execute(select(*cols))
            with dst.begin() as dconn:
                while rows := result.fetchmany(BATCH):
                    dconn.execute(table.insert(), [{c.name: _clean(v) for c, v in zip(cols, row)} for row in rows])
    print(f"{'Would copy' if args.dry_run else 'Copied'} {total} rows.")
    if not args.dry_run:
        print("Next: set DATABASE_URL to the target in backend/.env and restart VOXORA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
