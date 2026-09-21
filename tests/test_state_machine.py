"""trg_trips_bu / trg_trips_au: transitions, immutability, audit, driver status."""
import pytest

from taximan import services as svc
from taximan.db import DomainError, execute, fetch_one


def _status(conn, trip_id):
    return fetch_one(conn, "SELECT status FROM trips WHERE id = %s", (trip_id,))["status"]


def _driver_status(conn, driver_id):
    return fetch_one(conn, "SELECT status FROM drivers WHERE user_id = %s", (driver_id,))["status"]


def test_happy_path_and_audit(conn, make_driver, make_rider):
    d, r = make_driver(conn), make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    assert _status(conn, t) == "requested"
    svc.accept_trip(conn, t, d)
    assert _status(conn, t) == "accepted" and _driver_status(conn, d) == "on_trip"
    svc.start_trip(conn, t)
    fare = svc.complete_trip(conn, t, 3.3)
    assert fare >= 600 and _status(conn, t) == "completed"
    assert _driver_status(conn, d) == "available"
    row = fetch_one(conn, "SELECT current_zone_id FROM drivers WHERE user_id = %s", (d,))
    assert row["current_zone_id"] == 2, "driver ends where the trip ended"
    events = [(e["from_status"], e["to_status"]) for e in svc.trip_events(conn, t)]
    assert events == [(None, "requested"), ("requested", "accepted"), ("accepted", "in_progress"), ("in_progress", "completed")]


@pytest.mark.parametrize("bad_first_step", ["start", "complete"])
def test_cannot_skip_states(conn, make_driver, make_rider, bad_first_step):
    r = make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    with pytest.raises(DomainError) as e:
        if bad_first_step == "start":
            svc.start_trip(conn, t)
        else:
            execute(conn, "UPDATE trips SET status = 'completed' WHERE id = %s", (t,))
    assert e.value.code == "TRIP_INVALID_TRANSITION"


def test_terminal_states_are_immutable(conn, completed_trip):
    t = completed_trip["trip"]
    for sql in ["UPDATE trips SET status = 'cancelled', cancel_reason = 'rider' WHERE id = %s",
                "UPDATE trips SET fare_cents = 1 WHERE id = %s",
                "UPDATE trips SET status = 'requested' WHERE id = %s"]:
        with pytest.raises(DomainError) as e:
            execute(conn, sql, (t,))
        assert e.value.code == "TRIP_TERMINAL"


def test_cancel_paths(conn, make_driver, make_rider):
    d, r = make_driver(conn), make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    with pytest.raises(DomainError) as e:
        execute(conn, "UPDATE trips SET status = 'cancelled' WHERE id = %s", (t,))
    assert e.value.code == "TRIP_NEEDS_REASON"
    svc.accept_trip(conn, t, d)
    assert _driver_status(conn, d) == "on_trip"
    svc.cancel_trip(conn, t, "rider")
    assert _status(conn, t) == "cancelled" and _driver_status(conn, d) == "available"
    row = fetch_one(conn, "SELECT cancelled_at, cancel_reason FROM trips WHERE id = %s", (t,))
    assert row["cancelled_at"] is not None and row["cancel_reason"] == "rider"


def test_accept_requires_available_driver(conn, make_driver, make_rider):
    d = make_driver(conn, status="offline")
    r = make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    with pytest.raises(DomainError) as e:
        svc.accept_trip(conn, t, d)
    assert e.value.code == "DRIVER_UNAVAILABLE"


def test_driver_cannot_be_reassigned(conn, make_driver, make_rider):
    d1, d2, r = make_driver(conn), make_driver(conn), make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    svc.accept_trip(conn, t, d1)
    with pytest.raises(DomainError) as e:
        execute(conn, "UPDATE trips SET driver_id = %s WHERE id = %s", (d2, t))
    assert e.value.code == "TRIP_DRIVER_LOCKED"


def test_vehicle_must_belong_to_driver(conn, make_driver, make_rider):
    d1, d2, r = make_driver(conn), make_driver(conn), make_rider(conn)
    v2 = fetch_one(conn, "SELECT id FROM vehicles WHERE driver_id = %s AND is_active = 1", (d2,))["id"]
    t = svc.request_trip(conn, r, 1, 2)
    with pytest.raises(DomainError) as e:
        execute(conn, "UPDATE trips SET status = 'accepted', driver_id = %s, vehicle_id = %s WHERE id = %s", (d1, v2, t))
    assert e.value.code == "VEHICLE_MISMATCH"


def test_driver_status_rules(conn, make_driver):
    d = make_driver(conn, status="offline")
    execute(conn, "UPDATE drivers SET approved_at = NULL WHERE user_id = %s", (d,))
    with pytest.raises(DomainError) as e:
        svc.set_driver_status(conn, d, "available")
    assert e.value.code == "DRIVER_NOT_APPROVED"
    with pytest.raises(DomainError) as e:
        svc.set_driver_status(conn, d, "on_trip")
    assert e.value.code == "BAD_STATUS"
