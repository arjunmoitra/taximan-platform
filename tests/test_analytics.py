import pytest

from taximan.analytics import list_queries, run_query

QUERIES = list_queries()


def test_twelve_queries_exist():
    assert len(QUERIES) == 12


@pytest.mark.parametrize("path", QUERIES, ids=[p.stem for p in QUERIES])
def test_query_runs_and_returns_rows(conn, path):
    cols, rows, secs = run_query(conn, path)
    assert len(cols) >= 3
    assert len(rows) > 0, f"{path.name} returned no rows on the seed"
    assert secs < 10
