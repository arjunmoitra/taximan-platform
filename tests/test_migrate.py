import pytest

from taximan.migrate import applied, migrate, split_statements


def test_split_statements_handles_delimiter():
    sql = """
    CREATE TABLE a (x INT);
    DELIMITER $$
    CREATE TRIGGER t BEFORE INSERT ON a FOR EACH ROW BEGIN
        SET NEW.x = 1;
    END$$
    DELIMITER ;
    INSERT INTO a VALUES (2);
    """
    stmts = split_statements(sql)
    assert len(stmts) == 3
    assert stmts[1].startswith("CREATE TRIGGER") and "SET NEW.x = 1;" in stmts[1]
    assert stmts[2] == "INSERT INTO a VALUES (2)"


def test_migrations_are_idempotent(conn):
    assert migrate() == []
    names = list(applied(conn))
    assert names == ["001_schema.sql", "002_triggers.sql", "003_views.sql"]


def test_changed_migration_is_refused(tmp_path, conn):
    import hashlib
    from taximan.db import execute
    execute(conn, "INSERT INTO schema_migrations (filename, sha256) VALUES ('999_x.sql', %s)", (hashlib.sha256(b"old").hexdigest(),))
    conn.commit()
    (tmp_path / "999_x.sql").write_text("SELECT 1;")
    try:
        with pytest.raises(RuntimeError, match="different checksum"):
            migrate(conn, migrations_dir=tmp_path)
    finally:
        execute(conn, "DELETE FROM schema_migrations WHERE filename = '999_x.sql'")
        conn.commit()
