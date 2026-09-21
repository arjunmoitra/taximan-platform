"""Test fixtures. Tests run against a real MySQL (docker compose up -d) in a
separate database `taximan_test` that is dropped and rebuilt per session.
"""
import os

os.environ.setdefault("MYSQL_DATABASE", "taximan_test")

import pytest  # noqa: E402

from taximan import services as svc  # noqa: E402
from taximan.config import settings  # noqa: E402
from taximan.db import connect, execute, reset_pool, transaction  # noqa: E402
from taximan.generate import generate, load  # noqa: E402
from taximan.migrate import drop_all, migrate  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database(tmp_path_factory):
    assert settings.database.endswith("_test"), "refusing to run tests against a non test database"
    admin = connect()
    drop_all(admin)
    admin.close()
    migrate()
    reset_pool()
    data_dir = tmp_path_factory.mktemp("seed")
    generate(scale=0.02, seed=7, days=120, out_dir=data_dir)
    load(data_dir=data_dir, verbose=False)
    yield
    reset_pool()


@pytest.fixture()
def conn():
    """A dedicated connection in a transaction that is rolled back after the test."""
    c = connect()
    c.start_transaction()
    yield c
    c.rollback()
    c.close()


_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


@pytest.fixture()
def make_driver():
    def _make(conn, status="available", zone_id=1):
        n = _next()
        uid = svc.create_user(conn, email=f"t.driver.{n}.{os.getpid()}@example.com", phone_e164=f"+1777{n:07d}",
                              full_name=f"Test Driver {n}", password="password123")
        svc.register_driver(conn, uid, licence_no=f"T-{n}-{os.getpid()}", zone_id=zone_id)
        svc.approve_driver(conn, uid)
        svc.add_vehicle(conn, uid, plate=f"T{n}{os.getpid()}", make="Honda", model="Civic", model_year=2020)
        if status != "offline":
            svc.set_driver_status(conn, uid, "available", zone_id)
        return uid
    return _make


@pytest.fixture()
def make_rider():
    def _make(conn):
        n = _next()
        uid = svc.create_user(conn, email=f"t.rider.{n}.{os.getpid()}@example.com", phone_e164=f"+1776{n:07d}",
                              full_name=f"Test Rider {n}", password="password123")
        svc.register_rider(conn, uid, 1)
        return uid
    return _make


@pytest.fixture()
def completed_trip(conn, make_driver, make_rider):
    """A completed trip on the given connection (not committed)."""
    d = make_driver(conn)
    r = make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2, 1.0)
    svc.accept_trip(conn, t, d)
    svc.start_trip(conn, t)
    svc.complete_trip(conn, t, 5.0)
    return {"trip": t, "driver": d, "rider": r}
