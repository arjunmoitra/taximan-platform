"""Declarative rules: CHECK, UNIQUE, FOREIGN KEY, generated column."""
import pytest

from taximan import services as svc
from taximan.db import DomainError, execute


def test_email_and_phone_checks(conn):
    with pytest.raises(DomainError) as e:
        svc.create_user(conn, email="not-an-email", phone_e164="+17890000000", full_name="x", password="password123")
    assert e.value.code == "CHECK_VIOLATION"
    with pytest.raises(DomainError) as e:
        svc.create_user(conn, email="ok@example.com", phone_e164="5140000000", full_name="x", password="password123")
    assert e.value.code == "CHECK_VIOLATION"


def test_unique_email(conn):
    svc.create_user(conn, email="dup@example.com", phone_e164="+17890000001", full_name="a", password="password123")
    with pytest.raises(DomainError) as e:
        svc.create_user(conn, email="DUP@example.com", phone_e164="+17890000002", full_name="b", password="password123")
    assert e.value.code == "DUPLICATE"


def test_rating_score_range(conn, completed_trip):
    with pytest.raises(DomainError) as e:
        execute(conn, "INSERT INTO ratings (trip_id, rated_by, score) VALUES (%s, 'rider', 6)", (completed_trip["trip"],))
    assert e.value.code == "CHECK_VIOLATION"
    with pytest.raises(DomainError):
        execute(conn, "INSERT INTO ratings (trip_id, rated_by, score) VALUES (%s, 'rider', 0)", (completed_trip["trip"],))


def test_one_active_vehicle_per_driver(conn, make_driver):
    d = make_driver(conn)
    with pytest.raises(DomainError) as e:
        svc.add_vehicle(conn, d, plate="SECOND1", make="Kia", model="Soul", model_year=2022, replace_active=False)
    assert e.value.code == "DUPLICATE"
    # replacing is fine and leaves exactly one active
    svc.add_vehicle(conn, d, plate="SECOND2", make="Kia", model="Soul", model_year=2022, replace_active=True)
    from taximan.db import fetch_one
    row = fetch_one(conn, "SELECT SUM(is_active) AS active, COUNT(*) AS total FROM vehicles WHERE driver_id = %s", (d,))
    assert (row["active"], row["total"]) == (1, 2)


def test_foreign_keys_block_orphans(conn, make_rider):
    r = make_rider(conn)
    with pytest.raises(DomainError) as e:
        execute(conn, "INSERT INTO trips (rider_id, pickup_zone_id, dropoff_zone_id) VALUES (%s, 1, 999)", (r,))
    assert e.value.code == "FK_VIOLATION"
    with pytest.raises(DomainError) as e:
        execute(conn, "DELETE FROM zones WHERE id = 1")
    assert e.value.code == "FK_VIOLATION"


def test_completed_trip_needs_economics(conn, make_rider):
    r = make_rider(conn)
    with pytest.raises(DomainError) as e:
        execute(conn, "INSERT INTO trips (rider_id, pickup_zone_id, dropoff_zone_id, status, completed_at) "
                      "VALUES (%s, 1, 2, 'completed', NOW(3))", (r,))
    assert e.value.code == "CHECK_VIOLATION"


def test_surge_range(conn, make_rider):
    r = make_rider(conn)
    with pytest.raises(DomainError):
        svc.request_trip(conn, r, 1, 2, surge_multiplier=7.0)
