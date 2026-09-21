"""Run the analytical SQL in db/analytics and render the results."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import ANALYTICS_DIR
from .db import connect


def list_queries(directory: Path = ANALYTICS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def run_query(conn, path: Path) -> tuple[list[str], list[tuple], float]:
    sql = path.read_text(encoding="utf-8")
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return cols, rows, time.perf_counter() - t0


def run_all(only: str | None = None, max_rows: int = 15, console: Console | None = None) -> dict[str, float]:
    console = console or Console()
    timings: dict[str, float] = {}
    conn = connect()
    try:
        for path in list_queries():
            if only and only not in path.name:
                continue
            title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("- ").strip()
            cols, rows, secs = run_query(conn, path)
            timings[path.name] = secs
            table = Table(title=f"{title}   [{len(rows)} rows, {secs*1000:.0f} ms]", show_lines=False)
            for c in cols:
                table.add_column(c, overflow="fold")
            for r in rows[:max_rows]:
                table.add_row(*["" if v is None else str(v) for v in r])
            console.print(table)
    finally:
        conn.close()
    return timings
