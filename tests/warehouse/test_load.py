"""The statements sent to Snowflake, checked with a fake connection."""
import pytest

from taximan.warehouse import load
from taximan.warehouse.spec import TABLES


class FakeCursor:
    def __init__(self, log, copy_rows):
        self.log, self.copy_rows, self.last = log, copy_rows, ""

    def execute(self, sql):
        self.last = sql
        self.log.append(("execute", sql))

    def fetchall(self):
        return self.copy_rows if self.last.startswith("COPY") else []

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows_loaded=10):
        self.log = []
        self.copy_rows = [("trips.parquet", "LOADED", rows_loaded, rows_loaded, 0, 0, None, None, None, None)]

    def cursor(self):
        return FakeCursor(self.log, self.copy_rows)

    def execute_string(self, sql):
        self.log.append(("script", sql))
        return []


@pytest.fixture()
def parquet_dir(tmp_path):
    for t in TABLES:
        (tmp_path / f"{t.name}.parquet").write_bytes(b"PAR1")
    return tmp_path


def test_load_recreates_tables_then_puts_and_copies_each_table(parquet_dir):
    conn = FakeConn()
    loaded = load.load_raw(conn, parquet_dir)
    kinds = [k for k, _ in conn.log]
    assert kinds[0] == "script" and "CREATE OR REPLACE TABLE raw.trips" in conn.log[0][1]
    statements = [sql.split()[0] for k, sql in conn.log if k == "execute"]
    assert statements == ["PUT", "COPY"] * len(TABLES)
    assert loaded == {t.name: 10 for t in TABLES}


def test_put_does_not_recompress_and_overwrites(parquet_dir):
    sql = load.put_statement("trips", parquet_dir / "trips.parquet")
    assert "AUTO_COMPRESS = FALSE" in sql and "OVERWRITE = TRUE" in sql
    assert sql.startswith("PUT 'file://") and "@raw.taximan_stage/trips/" in sql


def test_copy_matches_columns_by_name_and_fails_loudly():
    sql = load.copy_statement("trips")
    assert "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE" in sql
    assert "ON_ERROR = ABORT_STATEMENT" in sql and "FORCE = TRUE" in sql
    assert "FORMAT_NAME = 'taximan.raw.taximan_parquet'" in sql


def test_missing_extract_is_reported_before_anything_is_sent(tmp_path):
    conn = FakeConn()
    with pytest.raises(FileNotFoundError, match="taximan warehouse extract"):
        load.load_raw(conn, tmp_path)
    assert conn.log == []


def test_paths_with_spaces_and_quotes_are_quoted(tmp_path):
    folder = tmp_path / "my data's folder"
    folder.mkdir()
    sql = load.put_statement("trips", folder / "trips.parquet")
    # spaces are fine inside the quoted literal, and the apostrophe is escaped so it cannot end it
    assert "my data\\'s folder" in sql
    assert sql.startswith("PUT 'file://") and "trips.parquet' @raw.taximan_stage" in sql


def test_views_build_in_name_order_with_as_of_first():
    conn = FakeConn()
    names = load.build_views(conn)
    assert names[0] == "00_as_of" and names == sorted(names) and len(names) == 13
    assert [k for k, _ in conn.log] == ["script"] * 13


def test_setup_runs_the_setup_script():
    conn = FakeConn()
    load.setup(conn)
    assert "CREATE WAREHOUSE IF NOT EXISTS taximan_wh" in conn.log[0][1]
