"""Command line entry point: `taximan --help`."""
from __future__ import annotations

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


if __name__ == "__main__":
    app()
