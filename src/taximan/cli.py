"""Command line entry point: `taximan --help`."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Taximan ride hailing data platform", no_args_is_help=True)
console = Console()


@app.command()
def migrate():
    """Apply pending SQL migrations from db/migrations."""
    from .migrate import migrate as _migrate

    ran = _migrate()
    console.print(f"applied {len(ran)} migration(s): {ran}" if ran else "database is up to date")


@app.command()
def seed(scale: float = typer.Option(1.0, help="1.0 = 20k riders, 2.5k drivers, 300k trips"),
         seed: int = 42, days: int = 365, keep_csv: bool = False):
    """Generate synthetic data and bulk load it (replaces existing rows)."""
    import time

    from .config import DATA_DIR
    from .db import connect
    from .generate import generate, load, reset

    t0 = time.perf_counter()
    counts = generate(scale=scale, seed=seed, days=days)
    console.print(f"generated {counts} in {time.perf_counter() - t0:.1f}s")
    conn = connect()
    try:
        reset(conn)
        load(conn=conn)
    finally:
        conn.close()
    if not keep_csv:
        for p in DATA_DIR.glob("*.csv"):
            p.unlink()
    console.print(f"done in {time.perf_counter() - t0:.1f}s")


@app.command()
def analytics(only: str = typer.Option(None, help="substring of the query file name"), rows: int = 15):
    """Run the analytical queries in db/analytics and print the results."""
    from .analytics import run_all

    timings = run_all(only=only, max_rows=rows, console=console)
    console.print({k: f"{v * 1000:.0f} ms" for k, v in timings.items()})


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Run the FastAPI service."""
    import uvicorn

    uvicorn.run("taximan.api:app", host=host, port=port, reload=reload)


@app.command()
def lab(which: str = typer.Argument(..., help="lost-update | double-booking | dispatch")):
    """Run a concurrency demonstration from the concurrency/ folder."""
    import runpy
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "concurrency"
    path = root / f"{which.replace('-', '_')}.py"
    if not path.exists():
        raise typer.BadParameter(f"unknown lab {which}; choose one of {[p.stem for p in root.glob('*.py')]}")
    runpy.run_path(str(path), run_name="__main__")

warehouse_app = typer.Typer(
    help="Optional Snowflake analytics layer. Needs: pip install -e '.[warehouse]'",
    no_args_is_help=True,
)
app.add_typer(warehouse_app, name="warehouse")


def _snowflake(with_context: bool = True):
    from .warehouse.config import ConfigError, SnowflakeConfig
    from .warehouse.load import connect as sf_connect

    try:
        cfg = SnowflakeConfig.from_env()
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"connecting to Snowflake as {cfg.user} ({cfg.auth_method})")
    return sf_connect(cfg, with_context=with_context)


@warehouse_app.command("setup")
def warehouse_setup():
    """Create the Snowflake warehouse, database, schemas, file format and stage (idempotent)."""
    from .warehouse import load

    conn = _snowflake(with_context=False)
    try:
        load.setup(conn)
    finally:
        conn.close()
    console.print("snowflake objects are in place")


@warehouse_app.command("extract")
def warehouse_extract(out: Path = typer.Option(None, help="directory for the Parquet files")):
    """Export the allowlisted, PII free columns from MySQL to Parquet."""
    from .warehouse.extract import WAREHOUSE_DIR, extract_all

    counts = extract_all(out or WAREHOUSE_DIR)
    console.print({k: f"{v:,}" for k, v in counts.items()})


@warehouse_app.command("load")
def warehouse_load(src: Path = typer.Option(None, help="directory holding the Parquet files")):
    """Recreate the RAW tables and load the extract (PUT then COPY INTO)."""
    from .warehouse import load
    from .warehouse.extract import WAREHOUSE_DIR

    conn = _snowflake()
    try:
        loaded = load.load_raw(conn, src or WAREHOUSE_DIR)
    finally:
        conn.close()
    console.print({k: f"{v:,}" for k, v in loaded.items()})


@warehouse_app.command("build")
def warehouse_build():
    """Create the ANALYTICS views."""
    from .warehouse import load

    conn = _snowflake()
    try:
        names = load.build_views(conn)
    finally:
        conn.close()
    console.print(f"created {len(names)} views: {', '.join(names)}")


@warehouse_app.command("check")
def warehouse_check():
    """Reconcile Snowflake against MySQL. Exits 1 if any number differs."""
    from .db import connect
    from .warehouse import load
    from .warehouse.reconcile import reconcile

    def mysql_one(sql: str):
        cur = mysql.cursor()
        try:
            cur.execute(sql)
            return cur.fetchone()
        finally:
            cur.close()

    mysql = connect()
    sf = _snowflake()
    try:
        results = reconcile(mysql_one, load.run_one(sf))
    finally:
        mysql.close()
        sf.close()
    bad = [r for r in results if not r.ok]
    for r in bad:
        console.print(f"[red]MISMATCH[/red] {r.table} {r.expression}: mysql={r.source} snowflake={r.target}")
    console.print(f"{len(results) - len(bad)} of {len(results)} checks match")
    if bad:
        raise typer.Exit(1)


@warehouse_app.command("all")
def warehouse_all():
    """Extract, load, build and check in one go (run `setup` once first)."""
    warehouse_extract(out=None)
    warehouse_load(src=None)
    warehouse_build()
    warehouse_check()


if __name__ == "__main__":
    app()
