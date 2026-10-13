"""Each Snowflake view must return what the MySQL query it ports returns.

Runs against a MySQL database seeded at scale 0.1. The ported SQL is transpiled to
DuckDB in strict mode and executed over the Parquet extract, see parity.py.
"""
import pytest
import parity
from taximan.warehouse.extract import extract_all


@pytest.fixture(scope="module")
def parquet_dir(parity_conn, tmp_path_factory):
    out = tmp_path_factory.mktemp("parquet")
    extract_all(out, conn=parity_conn)
    return out


@pytest.fixture(scope="module")
def duck(parquet_dir):
    con = parity.duckdb_from_parquet(parquet_dir)
    parity.build_views(con)
    return con


@pytest.fixture(scope="module")
def anchor(parity_conn):
    return parity.mysql_anchor(parity_conn)


def _mysql_rows(conn, path, anchor):
    cur = conn.cursor()
    try:
        cur.execute(parity.mysql_reference_sql(path, anchor))
        return cur.fetchall()
    finally:
        cur.close()


def test_every_original_query_has_a_view():
    views = {f"q{p.stem}" for p in parity.SF_ANALYTICS_DIR.glob("[0-9][0-9]_*.sql") if p.stem != "00_as_of"}
    assert {f"q{p.stem}" for p in parity.original_queries()} == views


@pytest.mark.parametrize("path", parity.original_queries(), ids=lambda p: p.stem)
def test_snowflake_view_matches_mysql(path, duck, parity_conn, anchor):
    expected = _mysql_rows(parity_conn, path, anchor)
    actual = duck.execute(f"SELECT * FROM {parity.view_name(path)}").fetchall()
    assert expected, f"{path.stem} is empty on the parity seed, so comparing it would prove nothing"
    problems = parity.compare(expected, actual)
    assert not problems, "\n".join(problems)
