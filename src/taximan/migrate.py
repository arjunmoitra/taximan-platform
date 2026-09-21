"""Forward only SQL migrations.

Files in db/migrations are applied in filename order. Each applied file is
recorded in schema_migrations with its sha256 so a changed file that was
already applied fails loudly instead of silently diverging.

The parser understands `DELIMITER $$` so trigger bodies can be written in
plain SQL files runnable by both this tool and the mysql client.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from mysql.connector.connection import MySQLConnection

from .config import MIGRATIONS_DIR
from .db import connect

_DELIM_RE = re.compile(r"^\s*DELIMITER\s+(\S+)\s*$", re.IGNORECASE)


def split_statements(sql: str) -> list[str]:
    """Split a script into statements, honouring DELIMITER lines."""
    statements: list[str] = []
    delim = ";"
    buf: list[str] = []
    for line in sql.splitlines():
        m = _DELIM_RE.match(line)
        if m:
            if "".join(buf).strip():
                statements.append("\n".join(buf).strip())
            buf = []
            delim = m.group(1)
            continue
        stripped = line.rstrip()
        if stripped.endswith(delim):
            buf.append(stripped[: -len(delim)])
            stmt = "\n".join(buf).strip()
            if stmt and not all(l.strip().startswith("--") or not l.strip() for l in stmt.splitlines()):
                statements.append(stmt)
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip()
    if tail and not all(l.strip().startswith("--") or not l.strip() for l in tail.splitlines()):
        statements.append(tail)
    return statements


def _ensure_table(conn: MySQLConnection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   VARCHAR(255) NOT NULL PRIMARY KEY,
                sha256     CHAR(64)     NOT NULL,
                applied_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
            ) ENGINE=InnoDB
            """
        )
    conn.commit()


def applied(conn: MySQLConnection) -> dict[str, str]:
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT filename, sha256 FROM schema_migrations ORDER BY filename")
        return {f: h for f, h in cur.fetchall()}


def migrate(conn: MySQLConnection | None = None, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns the filenames applied this run."""
    owned = conn is None
    conn = conn or connect()
    try:
        done = applied(conn)
        ran: list[str] = []
        for path in sorted(migrations_dir.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    raise RuntimeError(
                        f"{path.name} was already applied with a different checksum. "
                        "Migrations are immutable; add a new file instead."
                    )
                continue
            with conn.cursor() as cur:
                for stmt in split_statements(sql):
                    cur.execute(stmt)
                cur.execute(
                    "INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)",
                    (path.name, digest),
                )
            conn.commit()
            ran.append(path.name)
        return ran
    finally:
        if owned:
            conn.close()


def drop_all(conn: MySQLConnection) -> None:
    """Destroy every object in the current database. Test helper only."""
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE()")
        for name, ttype in cur.fetchall():
            if ttype == "VIEW":
                cur.execute(f"DROP VIEW IF EXISTS `{name}`")
            else:
                cur.execute(f"DROP TABLE IF EXISTS `{name}`")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
