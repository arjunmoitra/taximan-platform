"""Checks on the SQL files that need neither MySQL nor Snowflake."""
import re

import pytest
import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel

from taximan.warehouse import load
from taximan.warehouse.spec import BY_NAME, FORBIDDEN_COLUMNS, TABLES

SQL_FILES = sorted(load.SQL_DIR.rglob("*.sql"))
VIEW_FILES = sorted(load.ANALYTICS_SQL_DIR.glob("*.sql"))


def _parse(path):
    parsed = sqlglot.parse(path.read_text(encoding="utf-8"), read="snowflake", error_level=ErrorLevel.RAISE)
    # A ";" followed by a trailing comment makes sqlglot emit an empty Semicolon node. It is not a statement.
    return [s for s in parsed if s is not None and not isinstance(s, exp.Semicolon)]


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_parses_as_snowflake_sql(path):
    assert _parse(path), f"{path.name} contains no statements"


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_snowflake_connector_splits_files_the_same_way(path):
    # execute_string uses the connector's own splitter, so a stray semicolon in a
    # comment would split a statement in half. Two independent splitters must agree.
    from snowflake.connector.util_text import split_statements
    import io

    statements = [s for s, _ in split_statements(io.StringIO(path.read_text(encoding="utf-8")), remove_comments=True) if s.strip()]
    assert len(statements) == len(_parse(path))


def test_raw_ddl_matches_the_extract_spec():
    ddl = {}
    for stmt in _parse(load.SQL_DIR / "02_raw_tables.sql"):
        assert isinstance(stmt, exp.Create)
        table = stmt.this.this.name
        ddl[table] = [(c.name, c.args["kind"]) for c in stmt.this.expressions if isinstance(c, exp.ColumnDef)]
    assert set(ddl) == set(BY_NAME)
    for spec in TABLES:
        assert [n for n, _ in ddl[spec.name]] == spec.column_names, f"{spec.name} columns or order differ"
        for column, (_, kind) in zip(spec.columns, ddl[spec.name]):
            t = str(column.arrow)
            if t.startswith("timestamp"):
                assert kind.this == exp.DataType.Type.TIMESTAMPNTZ, (spec.name, column.name)
            elif t.startswith("decimal"):
                p, s = (int(x) for x in t[t.index("(") + 1 : -1].split(", "))
                assert kind.this == exp.DataType.Type.DECIMAL
                assert [int(e.this.this) for e in kind.expressions] == [p, s], (spec.name, column.name)
            elif t == "bool":
                assert kind.this == exp.DataType.Type.BOOLEAN
            elif t == "string":
                assert kind.this == exp.DataType.Type.VARCHAR
            else:
                assert kind.this in (exp.DataType.Type.INT, exp.DataType.Type.BIGINT), (spec.name, column.name)


def test_no_personal_data_columns_anywhere():
    for spec in TABLES:
        assert not FORBIDDEN_COLUMNS & set(spec.column_names), spec.name
    ddl_columns = {
        c.name for stmt in _parse(load.SQL_DIR / "02_raw_tables.sql") for c in stmt.find_all(exp.ColumnDef)
    }
    assert not FORBIDDEN_COLUMNS & ddl_columns


def test_extract_never_uses_select_star():
    assert all("*" not in spec.select_sql for spec in TABLES)


@pytest.mark.parametrize("path", VIEW_FILES, ids=lambda p: p.name)
def test_views_read_only_allowlisted_tables(path):
    allowed = {f"raw.{t}" for t in BY_NAME} | {"analytics.as_of"}
    for stmt in _parse(path):
        # CTE names are not real tables
        ctes = {c.alias for c in stmt.find_all(exp.CTE)}
        created = stmt.this  # the view being defined, which is written to, not read
        tables = {
            f"{t.db}.{t.name}".lower() if t.db else t.name.lower()
            for t in stmt.find_all(exp.Table)
            if t.name not in ctes and t is not created
        }
        assert tables <= allowed, f"{path.name} reads {sorted(tables - allowed)}"


@pytest.mark.parametrize("path", VIEW_FILES, ids=lambda p: p.name)
def test_views_never_read_the_wall_clock(path):
    # Windows hang off analytics.as_of so a reload of the same extract gives the same numbers.
    code = "\n".join(line.split("--")[0] for line in path.read_text(encoding="utf-8").splitlines())
    assert not re.search(r"\b(CURRENT_TIMESTAMP|CURRENT_DATE|SYSDATE|GETDATE|UTC_TIMESTAMP|NOW)\b", code, re.I)


def test_as_of_builds_first():
    assert [p.name for p in VIEW_FILES][0] == "00_as_of.sql"
