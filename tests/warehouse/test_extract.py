import pyarrow.parquet as pq
import pytest

from taximan.warehouse.extract import extract_all, extract_table
from taximan.warehouse.spec import FORBIDDEN_COLUMNS, TABLES, TableSpec


@pytest.fixture(scope="module")
def extracted(parity_conn, tmp_path_factory):
    out = tmp_path_factory.mktemp("extract")
    return out, extract_all(out, conn=parity_conn)


@pytest.mark.parametrize("spec", TABLES, ids=lambda s: s.name)
def test_row_counts_match_mysql(spec, extracted, parity_conn):
    out, counts = extracted
    cur = parity_conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM `{spec.name}`")
    expected = cur.fetchone()[0]
    cur.close()
    assert counts[spec.name] == expected > 0
    assert pq.read_metadata(out / f"{spec.name}.parquet").num_rows == expected


@pytest.mark.parametrize("spec", TABLES, ids=lambda s: s.name)
def test_parquet_schema_is_the_allowlist(spec, extracted):
    out, _ = extracted
    schema = pq.read_schema(out / f"{spec.name}.parquet")
    assert schema.names == spec.column_names
    assert not FORBIDDEN_COLUMNS & set(schema.names)
    assert schema.equals(spec.schema)


def test_extract_is_ordered_by_primary_key(extracted):
    out, _ = extracted
    ids = pq.read_table(out / "trips.parquet", columns=["id"]).column("id").to_pylist()
    assert ids == sorted(ids)


class _FakeCursor:
    def __init__(self, rows):
        self.rows, self.executed = list(rows), None

    def execute(self, sql):
        self.executed = sql

    def fetchmany(self, n):
        out, self.rows = self.rows[:n], self.rows[n:]
        return out

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self.cur = _FakeCursor(rows)

    def cursor(self):
        return self.cur


def test_empty_table_still_writes_a_valid_file(tmp_path):
    spec = next(t for t in TABLES if t.name == "zones")
    assert extract_table(_FakeConn([]), spec, tmp_path) == 0
    assert pq.read_schema(tmp_path / "zones.parquet").equals(spec.schema)


def test_chunking_does_not_lose_rows(tmp_path):
    from decimal import Decimal

    spec = next(t for t in TABLES if t.name == "zones")
    rows = [(i, "Montreal", f"Zone {i}", Decimal("45.500000"), Decimal("-73.570000")) for i in range(1, 11)]
    assert extract_table(_FakeConn(rows), spec, tmp_path, chunk_rows=3) == 10
    assert pq.read_table(tmp_path / "zones.parquet").num_rows == 10
