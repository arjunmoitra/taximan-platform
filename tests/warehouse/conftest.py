"""A larger, separate MySQL database for the parity test.

The shared taximan_test database is too small for several queries to return any
rows (Q02 needs 50 requests per zone and hour), and a comparison of two empty
results proves nothing. This one is seeded at scale 0.1 and dropped afterwards.
"""
import mysql.connector
import pytest
from helpers import make_rating_drop

# These tests need the optional extras (pip install -e ".[warehouse]"). Without them the
# folder is skipped instead of failing at import, so a plain `.[dev]` install still passes.
try:
    import duckdb, pyarrow, snowflake.connector, sqlglot  # noqa: E401,F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]

from taximan.config import Settings, settings
from taximan.db import connect
from taximan.generate import generate, load
from taximan.migrate import drop_all, migrate

PARITY_DB = "taximan_parity_test"


@pytest.fixture(scope="session")
def parity_conn(tmp_path_factory):
    kwargs = settings.connect_kwargs()
    kwargs.pop("database")
    admin = mysql.connector.connect(**kwargs)
    cur = admin.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {PARITY_DB}")
    cur.close()
    conn = connect(Settings(database=PARITY_DB))
    drop_all(conn)
    migrate(conn)
    data_dir = tmp_path_factory.mktemp("parity_seed")
    generate(scale=0.1, seed=11, days=120, out_dir=data_dir)
    load(data_dir=data_dir, conn=conn, verbose=False)
    # Q11 flags a driver only by chance in generated data, so build one. Otherwise the
    # comparison for that query would be between two empty results.
    make_rating_drop(conn)
    conn.commit()
    yield conn
    conn.close()
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {PARITY_DB}")
    cur.close()
    admin.close()
