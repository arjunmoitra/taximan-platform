"""The reconciliation must pass on a faithful copy and fail on a damaged one."""
import pytest
import parity
from taximan.warehouse.extract import extract_all
from taximan.warehouse.reconcile import CHECKS, reconcile


@pytest.fixture(scope="module")
def parquet_dir(parity_conn, tmp_path_factory):
    out = tmp_path_factory.mktemp("recon")
    extract_all(out, conn=parity_conn)
    return out


def _mysql(conn):
    def run(sql):
        cur = conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchone()
        finally:
            cur.close()

    return run


def _duck(con):
    return lambda sql: con.execute(sql).fetchone()


def test_a_faithful_copy_reconciles(parity_conn, parquet_dir):
    results = reconcile(_mysql(parity_conn), _duck(parity.duckdb_from_parquet(parquet_dir)))
    assert len(results) == sum(len(v) for v in CHECKS.values())
    assert [r for r in results if not r.ok] == []


def test_a_changed_amount_is_caught(parity_conn, parquet_dir):
    con = parity.duckdb_from_parquet(parquet_dir)
    con.execute("UPDATE raw.trips SET fare_cents = fare_cents + 1 WHERE id = (SELECT MIN(id) FROM raw.trips WHERE fare_cents IS NOT NULL)")
    bad = [r for r in reconcile(_mysql(parity_conn), _duck(con)) if not r.ok]
    assert [(r.table, r.expression) for r in bad] == [("trips", "SUM(fare_cents)")]


def test_a_shifted_timestamp_is_caught(parity_conn, parquet_dir):
    # What a Parquet timestamp loaded with the wrong time zone or unit would look like.
    con = parity.duckdb_from_parquet(parquet_dir)
    con.execute("UPDATE raw.trips SET requested_at = requested_at + INTERVAL 5 HOUR")
    bad = {(r.table, r.expression) for r in reconcile(_mysql(parity_conn), _duck(con)) if not r.ok}
    assert ("trips", "MIN(requested_at)") in bad and ("trips", "MAX(requested_at)") in bad


def test_a_dropped_row_is_caught(parity_conn, parquet_dir):
    con = parity.duckdb_from_parquet(parquet_dir)
    con.execute("DELETE FROM raw.payments WHERE id = (SELECT MIN(id) FROM raw.payments)")
    bad = {(r.table, r.expression) for r in reconcile(_mysql(parity_conn), _duck(con)) if not r.ok}
    assert ("payments", "COUNT(*)") in bad
