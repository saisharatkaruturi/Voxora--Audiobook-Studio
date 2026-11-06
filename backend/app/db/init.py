"""Database initialization: apply Alembic migrations (creating the schema on first run)."""

from __future__ import annotations

from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings
from app.core.logging import get_logger
from app.db.base import Base
from app.db.session import get_engine

log = get_logger(__name__)


def init_db() -> None:
    import app.models  # noqa: F401  (register models)

    engine = get_engine()
    alembic_ini = BACKEND_DIR / "alembic.ini"
    if alembic_ini.exists() and (BACKEND_DIR / "migrations" / "versions").exists() and any((BACKEND_DIR / "migrations" / "versions").glob("*.py")):
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(engine)
        _add_missing_columns(engine)
    Path(BACKEND_DIR / "data").mkdir(exist_ok=True)


def _add_missing_columns(engine) -> None:
    """create_all() never alters existing tables: add any new *nullable* model
    columns an older database lacks (additive only -- nothing is changed or dropped)."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or not col.nullable:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}')
                log.info("db.column_added", table=table.name, column=col.name)
                # ...and its index (e.g. a unique lookup key); safe on a column that's all NULL.
                for index in table.indexes:
                    if [c.name for c in index.columns] == [col.name]:
                        index.create(conn, checkfirst=True)
