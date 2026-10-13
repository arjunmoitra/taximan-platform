"""MySQL to Parquet, using only the columns on the allowlist in spec.py."""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..config import DATA_DIR
from ..db import connect
from .spec import TABLES, TableSpec

WAREHOUSE_DIR = DATA_DIR / "warehouse"
CHUNK_ROWS = 50_000


def _to_arrow(rows: list[tuple], spec: TableSpec) -> pa.Table:
    columns = list(zip(*rows)) if rows else [()] * len(spec.columns)
    arrays = []
    for column, values in zip(spec.columns, columns):
        if pa.types.is_boolean(column.arrow):  # TINYINT(1) arrives as 0 / 1
            values = [None if v is None else bool(v) for v in values]
        arrays.append(pa.array(values, type=column.arrow))
    return pa.Table.from_arrays(arrays, schema=spec.schema)


def extract_table(conn, spec: TableSpec, out_dir: Path, chunk_rows: int = CHUNK_ROWS) -> int:
    """Stream one table to <out_dir>/<table>.parquet and return its row count."""
    path = out_dir / f"{spec.name}.parquet"
    total = 0
    cur = conn.cursor()
    try:
        cur.execute(spec.select_sql)
        with pq.ParquetWriter(path, spec.schema, compression="snappy") as writer:
            while True:
                rows = cur.fetchmany(chunk_rows)
                if not rows:
                    break
                writer.write_table(_to_arrow(rows, spec))
                total += len(rows)
    finally:
        cur.close()
    return total


def extract_all(out_dir: Path = WAREHOUSE_DIR, conn=None) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    owned = conn is None
    conn = conn or connect()
    try:
        return {spec.name: extract_table(conn, spec, out_dir) for spec in TABLES}
    finally:
        if owned:
            conn.close()
