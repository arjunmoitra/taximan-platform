import pytest
from helpers import make_rating_drop

from taximan.analytics import list_queries, run_query

QUERIES = list_queries()


def test_twelve_queries_exist():
    assert len(QUERIES) == 12


@pytest.mark.parametrize("path", QUERIES, ids=[p.stem for p in QUERIES])
def test_query_runs_and_returns_rows(conn, path):
    cols, rows, secs = run_query(conn, path)
    assert len(cols) >= 3
    if path.stem != "11_driver_rating_trend":
        assert len(rows) > 0, f"{path.name} returned no rows on the seed"
    assert secs < 10


def test_q11_flags_a_driver_whose_recent_ratings_drop(conn):
    # Whether the seed contains such a driver depends on the date it was generated, so the
    # row count above is not asserted for Q11. This builds the case instead.
    driver_id = make_rating_drop(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT full_name FROM users WHERE id = %s", (driver_id,))
        name = cur.fetchone()[0]
    path = next(p for p in QUERIES if p.stem == "11_driver_rating_trend")
    cols, rows, _ = run_query(conn, path)
    mine = [dict(zip(cols, r)) for r in rows if r[cols.index("full_name")] == name]
    assert mine, f"driver {driver_id} ({name}) was not flagged. Rows: {rows}"
    assert mine[0]["total_ratings"] == 40
    assert float(mine[0]["prior_20_avg"]) == 5.0
    assert float(mine[0]["last_20_avg"]) == 3.0
    assert float(mine[0]["delta"]) == -2.0
