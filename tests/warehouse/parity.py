"""Helpers that check the Snowflake views against the MySQL queries they port.

Snowflake itself is not needed. The ported SQL is transpiled to DuckDB in strict
mode (any construct sqlglot cannot translate raises instead of being silently
dropped), run over the same Parquet extract, and compared to the original MySQL
query row for row. That proves the logic of the port. It does not prove
Snowflake specific behaviour, which only a live run can.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import sqlglot
from sqlglot.errors import ErrorLevel

from taximan.config import ANALYTICS_DIR, PROJECT_ROOT
from taximan.warehouse.spec import TABLES

SF_ANALYTICS_DIR = PROJECT_ROOT / "warehouse" / "snowflake" / "analytics"


def to_duckdb(snowflake_sql: str) -> list[str]:
    """Snowflake to DuckDB. Raises on anything sqlglot cannot translate faithfully."""
    return sqlglot.transpile(snowflake_sql, read="snowflake", write="duckdb", unsupported_level=ErrorLevel.RAISE)


def duckdb_from_parquet(parquet_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE SCHEMA analytics")
    for spec in TABLES:
        cols = ", ".join(
            f"CAST({c.name} AS TIMESTAMP) AS {c.name}" if str(c.arrow).startswith("timestamp") else c.name
            for c in spec.columns
        )
        path = (parquet_dir / f"{spec.name}.parquet").as_posix()
        con.execute(f"CREATE TABLE raw.{spec.name} AS SELECT {cols} FROM read_parquet('{path}')")
    return con


def build_views(con: duckdb.DuckDBPyConnection) -> list[str]:
    names = []
    for path in sorted(SF_ANALYTICS_DIR.glob("*.sql")):
        for stmt in to_duckdb(path.read_text(encoding="utf-8")):
            con.execute(stmt)
        names.append(path.stem)
    return names


def view_name(sql_path: Path) -> str:
    return f"analytics.q{sql_path.stem}"


def mysql_reference_sql(path: Path, anchor: datetime) -> str:
    """The original query with the three differences that are deliberate.

    * UTC_TIMESTAMP() becomes the data anchor, as in analytics.as_of
    * LIMIT is removed so the whole result is compared, not the top rows
    * users.full_name becomes users.id, because the warehouse carries no names
    """
    sql = path.read_text(encoding="utf-8")
    literal = f"CAST('{anchor:%Y-%m-%d %H:%M:%S.%f}' AS DATETIME(3))"
    sql = sql.replace("UTC_TIMESTAMP()", literal)
    sql = re.sub(r"\bLIMIT\s+\d+\s*;?\s*$", "", sql.strip(), flags=re.IGNORECASE)
    return sql.replace("u.full_name", "u.id")


def mysql_anchor(conn) -> datetime:
    cur = conn.cursor()
    try:
        cur.execute("SELECT MAX(requested_at) FROM trips")
        return cur.fetchone()[0]
    finally:
        cur.close()


def original_queries() -> list[Path]:
    return sorted(ANALYTICS_DIR.glob("*.sql"))


# --- comparison -------------------------------------------------------------

def _is_number(v: object) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _tolerance(mysql_value: object) -> float:
    """One unit in the last digit MySQL reported. Exact for counts and integers."""
    if isinstance(mysql_value, Decimal):
        exponent = mysql_value.as_tuple().exponent
        return 0.0 if exponent >= 0 else 1.01 * 10 ** exponent
    if isinstance(mysql_value, float):  # a ROUND over DOUBLE, reported to at most 3 digits here
        return 1.01e-3
    return 0.0


def _signature(row: tuple) -> tuple:
    out = []
    for v in row:
        if _is_number(v):
            continue
        out.append(v.isoformat() if isinstance(v, (date, datetime)) else v)
    return tuple(out)


def _numbers(row: tuple) -> list:
    return [v for v in row if _is_number(v)]


def compare(mysql_rows: list[tuple], other_rows: list[tuple]) -> list[str]:
    """Return a list of problems, empty when the two results agree.

    Rows are matched on their non numeric cells (strings, dates, NULLs) and the
    numeric cells must then agree to within one unit of the last reported digit.
    Row order is not compared, because ties may order differently.
    """
    problems: list[str] = []
    if len(mysql_rows) != len(other_rows):
        problems.append(f"row count differs: mysql={len(mysql_rows)} other={len(other_rows)}")
    buckets: dict[tuple, list[list]] = defaultdict(list)
    for row in other_rows:
        buckets[_signature(row)].append(_numbers(row))
    for row in mysql_rows:
        candidates = buckets.get(_signature(row))
        want = _numbers(row)
        if not candidates:
            problems.append(f"no matching row for {row}")
            continue
        for i, got in enumerate(candidates):
            if len(got) == len(want) and all(abs(float(g) - float(w)) <= _tolerance(w) + 1e-12 for g, w in zip(got, want)):
                candidates.pop(i)
                break
        else:
            problems.append(f"values differ for {row}: closest other rows {candidates[:2]}")
        if len(problems) >= 8:
            break
    return problems
