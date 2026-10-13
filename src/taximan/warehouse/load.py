"""Create the Snowflake objects, load the Parquet extract and build the views.

Every function takes an open Snowflake connection, so the statement sequence can
be unit tested with a fake and run for real from the CLI. The snowflake
connector is imported lazily so the rest of the package works without it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..config import PROJECT_ROOT
from .config import SnowflakeConfig
from .reconcile import RunOne
from .spec import TABLES

SQL_DIR = PROJECT_ROOT / "warehouse" / "snowflake"
ANALYTICS_SQL_DIR = SQL_DIR / "analytics"
STAGE = "raw.taximan_stage"
FILE_FORMAT = "taximan.raw.taximan_parquet"


def connect(cfg: SnowflakeConfig, with_context: bool = True):
    import snowflake.connector

    return snowflake.connector.connect(**cfg.connect_kwargs(with_context=with_context))


def run_script(conn, path: Path) -> None:
    for cur in conn.execute_string(path.read_text(encoding="utf-8")):
        cur.close()


def setup(conn) -> None:
    run_script(conn, SQL_DIR / "01_setup.sql")


def create_tables(conn) -> None:
    run_script(conn, SQL_DIR / "02_raw_tables.sql")


def view_scripts() -> list[Path]:
    return sorted(ANALYTICS_SQL_DIR.glob("*.sql"))


def build_views(conn, scripts: Iterable[Path] | None = None) -> list[str]:
    scripts = list(scripts) if scripts is not None else view_scripts()
    for path in scripts:
        run_script(conn, path)
    return [p.stem for p in scripts]


def _quote_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "\\'")


def put_statement(table: str, path: Path) -> str:
    # Parquet is already compressed, so tell PUT not to gzip it a second time.
    return f"PUT 'file://{_quote_path(path)}' @{STAGE}/{table}/ AUTO_COMPRESS = FALSE OVERWRITE = TRUE"


def copy_statement(table: str) -> str:
    # FORCE reloads files Snowflake has already seen, because a reload of the
    # same extract is the normal case here. ON_ERROR aborts instead of skipping
    # rows, so a bad load fails loudly.
    return (
        f"COPY INTO raw.{table} FROM @{STAGE}/{table}/ "
        f"FILE_FORMAT = (FORMAT_NAME = '{FILE_FORMAT}') "
        "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE FORCE = TRUE ON_ERROR = ABORT_STATEMENT"
    )


def load_raw(conn, parquet_dir: Path) -> dict[str, int]:
    """Recreate the RAW tables, stage every Parquet file and COPY it in.

    Returns rows loaded per table as reported by COPY. `taximan warehouse check`
    is the real verification.
    """
    missing = [t.name for t in TABLES if not (parquet_dir / f"{t.name}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"no extract for {missing} in {parquet_dir}. Run `taximan warehouse extract`.")
    create_tables(conn)
    loaded: dict[str, int] = {}
    for spec in TABLES:
        cur = conn.cursor()
        try:
            cur.execute(put_statement(spec.name, parquet_dir / f"{spec.name}.parquet"))
            cur.execute(copy_statement(spec.name))
            # COPY returns one row per file: (file, status, rows_parsed, rows_loaded, ...)
            loaded[spec.name] = sum(int(row[3]) for row in cur.fetchall() if row[1] == "LOADED")
        finally:
            cur.close()
    return loaded


def run_one(conn) -> RunOne:
    """Adapt a Snowflake connection to the reconcile interface."""

    def _run(sql: str) -> tuple:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchone()
        finally:
            cur.close()

    return _run
