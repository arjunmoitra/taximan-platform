"""Connection pool and transaction helpers.

Every write path in the platform goes through `transaction()`, which commits on
success and rolls back on any exception. Nothing else calls commit().
"""
from __future__ import annotations

import contextlib
from typing import Iterator

import mysql.connector
from mysql.connector import pooling
from mysql.connector.connection import MySQLConnection

from .config import Settings, settings

_pool: pooling.MySQLConnectionPool | None = None


class DomainError(Exception):
    """A business rule rejected the write. `code` is the token before the colon
    in the trigger's MESSAGE_TEXT, e.g. DRIVER_UNAVAILABLE."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def get_pool(cfg: Settings = settings) -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="taximan", pool_size=cfg.pool_size, **cfg.connect_kwargs()
        )
    return _pool


def reset_pool() -> None:
    global _pool
    _pool = None


def connect(cfg: Settings = settings) -> MySQLConnection:
    """A dedicated, non pooled connection. Used by the concurrency lab and tests
    when two independent sessions are the whole point."""
    return mysql.connector.connect(**cfg.connect_kwargs())


def translate_error(exc: mysql.connector.Error) -> Exception:
    """Map SQLSTATE 45000 (our SIGNALs) and constraint violations to DomainError."""
    if exc.sqlstate == "45000":
        code, _, msg = exc.msg.partition(":")
        return DomainError(code.strip(), msg.strip() or exc.msg)
    if exc.errno == 3819:  # CHECK constraint violated
        return DomainError("CHECK_VIOLATION", exc.msg)
    if exc.errno == 1062:  # duplicate key
        return DomainError("DUPLICATE", exc.msg)
    if exc.errno in (1451, 1452):  # FK violations
        return DomainError("FK_VIOLATION", exc.msg)
    return exc


@contextlib.contextmanager
def transaction(conn: MySQLConnection | None = None) -> Iterator[MySQLConnection]:
    """Yield a connection inside a transaction. Commit on success, rollback on error.

    If `conn` is given it is used as is (caller owns it). Otherwise a pooled
    connection is taken and returned.
    """
    owned = conn is None
    if owned:
        conn = get_pool().get_connection()
    try:
        conn.start_transaction()
        yield conn
        conn.commit()
    except mysql.connector.Error as exc:
        conn.rollback()
        raise translate_error(exc) from exc
    except BaseException:
        conn.rollback()
        raise
    finally:
        if owned:
            conn.close()


def fetch_all(conn: MySQLConnection, sql: str, params: tuple | dict = ()) -> list[dict]:
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except mysql.connector.Error as exc:
        raise translate_error(exc) from exc


def fetch_one(conn: MySQLConnection, sql: str, params: tuple | dict = ()) -> dict | None:
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    except mysql.connector.Error as exc:
        raise translate_error(exc) from exc


def execute(conn: MySQLConnection, sql: str, params: tuple | dict = ()) -> int:
    """Run one statement. Returns lastrowid for inserts, else the affected rowcount.

    A statement rejected by a trigger or constraint raises DomainError here, at
    the statement, so callers can catch it. MySQL rolls back only that statement;
    the enclosing transaction stays usable.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid if cur.lastrowid else cur.rowcount
    except mysql.connector.Error as exc:
        raise translate_error(exc) from exc
