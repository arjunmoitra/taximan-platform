"""Ratings and payments: lookups enforced by triggers."""
import pytest

from taximan import services as svc
from taximan.db import DomainError, execute, fetch_one


def test_rating_only_on_completed(conn, make_driver, make_rider):
    d, r = make_driver(conn), make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    svc.accept_trip(conn, t, d)
    with pytest.raises(DomainError) as e:
        svc.rate_trip(conn, t, "rider", 5)
    assert e.value.code == "RATING_NOT_COMPLETED"


def test_rating_updates_aggregates_and_is_immutable(conn, completed_trip):
    t, d, r = completed_trip["trip"], completed_trip["driver"], completed_trip["rider"]
    svc.rate_trip(conn, t, "rider", 4)
    svc.rate_trip(conn, t, "driver", 5)
    assert svc.driver_profile(conn, d)["rating_avg"] == 4
    assert svc.rider_profile(conn, r)["rating_avg"] == 5
    with pytest.raises(DomainError) as e:
        svc.rate_trip(conn, t, "rider", 1)
    assert e.value.code == "DUPLICATE"
    with pytest.raises(DomainError) as e:
        execute(conn, "UPDATE ratings SET score = 1 WHERE trip_id = %s", (t,))
    assert e.value.code == "RATING_IMMUTABLE"
    execute(conn, "DELETE FROM ratings WHERE trip_id = %s AND rated_by = 'rider'", (t,))
    prof = svc.driver_profile(conn, d)
    assert prof["rating_count"] == 0 and prof["rating_avg"] is None


def test_payment_rules(conn, completed_trip, make_rider):
    t = completed_trip["trip"]
    fare = fetch_one(conn, "SELECT fare_cents FROM trips WHERE id = %s", (t,))["fare_cents"]
    with pytest.raises(DomainError) as e:
        execute(conn, "INSERT INTO payments (trip_id, amount_cents, method) VALUES (%s, %s, 'card')", (t, fare + 1))
    assert e.value.code == "PAYMENT_AMOUNT_MISMATCH"
    svc.record_payment(conn, t, "card", capture=False)
    with pytest.raises(DomainError) as e:
        svc.record_payment(conn, t, "cash")
    assert e.value.code == "DUPLICATE"
    with pytest.raises(DomainError) as e:
        svc.refund_payment(conn, t)  # pending -> refunded is not allowed
    assert e.value.code == "PAYMENT_INVALID_TRANSITION"
    svc.capture_payment(conn, t)
    row = fetch_one(conn, "SELECT status, captured_at FROM payments WHERE trip_id = %s", (t,))
    assert row["status"] == "captured" and row["captured_at"] is not None
    svc.refund_payment(conn, t)
    with pytest.raises(DomainError) as e:
        execute(conn, "UPDATE payments SET amount_cents = 1 WHERE trip_id = %s", (t,))
    assert e.value.code == "PAYMENT_IMMUTABLE"


def test_payment_needs_completed_trip(conn, make_rider):
    r = make_rider(conn)
    t = svc.request_trip(conn, r, 1, 2)
    with pytest.raises(DomainError) as e:
        execute(conn, "INSERT INTO payments (trip_id, amount_cents, method) VALUES (%s, 600, 'card')", (t,))
    assert e.value.code == "PAYMENT_NOT_COMPLETED"
