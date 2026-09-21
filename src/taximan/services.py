"""Domain operations. Each function takes an open connection inside a
transaction (see db.transaction) and issues parameterised SQL only.

Concurrency contract
--------------------
* accept_trip locks the trip row (FOR UPDATE) and the trigger locks the driver
  row (FOR UPDATE). Two concurrent accepts for the same driver serialise on the
  driver lock; the second sees status 'on_trip' and is rejected with
  DRIVER_UNAVAILABLE. See concurrency/double_booking.py for the proof.
* dispatch_trip uses SELECT ... FOR UPDATE SKIP LOCKED so many dispatchers can
  run in parallel without picking the same driver.
* Rating aggregates are updated by trigger with `col = col + x`, never
  read-modify-write in Python. See concurrency/lost_update.py.
"""
from __future__ import annotations

import bcrypt
from mysql.connector.connection import MySQLConnection

from .db import DomainError, execute, fetch_all, fetch_one
from .pricing import quote_cents


# The database is the only clock. Application hosts and the MySQL server can
# drift by tens of milliseconds, and trg_trips_bu enforces timestamp order, so
# every lifecycle timestamp is written by MySQL (CURRENT_TIMESTAMP(3)).


# --------------------------------------------------------------------------- users

def create_user(conn: MySQLConnection, *, email: str, phone_e164: str, full_name: str, password: str) -> int:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    return execute(
        conn,
        "INSERT INTO users (email, phone_e164, full_name, password_hash) VALUES (%s, %s, %s, %s)",
        (email.lower().strip(), phone_e164, full_name.strip(), pw_hash),
    )


def verify_password(conn: MySQLConnection, email: str, password: str) -> int | None:
    row = fetch_one(conn, "SELECT id, password_hash FROM users WHERE email = %s", (email.lower().strip(),))
    if row and bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return row["id"]
    return None


def register_rider(conn: MySQLConnection, user_id: int, home_zone_id: int | None = None) -> None:
    execute(conn, "INSERT INTO riders (user_id, home_zone_id) VALUES (%s, %s)", (user_id, home_zone_id))


def register_driver(conn: MySQLConnection, user_id: int, licence_no: str, zone_id: int | None = None) -> None:
    execute(
        conn,
        "INSERT INTO drivers (user_id, licence_no, current_zone_id) VALUES (%s, %s, %s)",
        (user_id, licence_no, zone_id),
    )


def approve_driver(conn: MySQLConnection, driver_id: int) -> None:
    n = execute(conn, "UPDATE drivers SET approved_at = CURRENT_TIMESTAMP(3) WHERE user_id = %s AND approved_at IS NULL", (driver_id,))
    if n == 0:
        raise DomainError("NOT_FOUND", "driver not found or already approved")


def set_driver_status(conn: MySQLConnection, driver_id: int, status: str, zone_id: int | None = None) -> None:
    if status not in ("offline", "available"):
        raise DomainError("BAD_STATUS", "drivers can only set themselves offline or available")
    n = execute(
        conn,
        "UPDATE drivers SET status = %s, current_zone_id = COALESCE(%s, current_zone_id) "
        "WHERE user_id = %s AND status <> 'on_trip'",
        (status, zone_id, driver_id),
    )
    if n == 0:
        raise DomainError("DRIVER_ON_TRIP", "cannot change status while on a trip")


def add_vehicle(conn: MySQLConnection, driver_id: int, *, plate: str, make: str, model: str,
                model_year: int, seats: int = 4, replace_active: bool = True) -> int:
    if replace_active:
        execute(conn, "UPDATE vehicles SET is_active = 0 WHERE driver_id = %s AND is_active = 1", (driver_id,))
    return execute(
        conn,
        "INSERT INTO vehicles (driver_id, plate, make, model, model_year, seats, is_active) VALUES (%s,%s,%s,%s,%s,%s,1)",
        (driver_id, plate.upper().replace(" ", ""), make, model, model_year, seats),
    )


# --------------------------------------------------------------------------- trips

def request_trip(conn: MySQLConnection, rider_id: int, pickup_zone_id: int, dropoff_zone_id: int,
                 surge_multiplier: float = 1.0) -> int:
    return execute(
        conn,
        "INSERT INTO trips (rider_id, pickup_zone_id, dropoff_zone_id, surge_multiplier) VALUES (%s, %s, %s, %s)",
        (rider_id, pickup_zone_id, dropoff_zone_id, surge_multiplier),
    )


def accept_trip(conn: MySQLConnection, trip_id: int, driver_id: int) -> None:
    trip = fetch_one(conn, "SELECT id, status FROM trips WHERE id = %s FOR UPDATE", (trip_id,))
    if trip is None:
        raise DomainError("NOT_FOUND", "trip not found")
    if trip["status"] != "requested":
        raise DomainError("TRIP_INVALID_TRANSITION", f"trip is {trip['status']}, not requested")
    vehicle = fetch_one(conn, "SELECT id FROM vehicles WHERE driver_id = %s AND is_active = 1", (driver_id,))
    if vehicle is None:
        raise DomainError("NO_ACTIVE_VEHICLE", "driver has no active vehicle")
    # trg_trips_bu takes FOR UPDATE on the driver row and validates availability.
    execute(
        conn,
        "UPDATE trips SET status = 'accepted', driver_id = %s, vehicle_id = %s WHERE id = %s",
        (driver_id, vehicle["id"], trip_id),
    )


def dispatch_trip(conn: MySQLConnection, trip_id: int) -> int:
    """Pick the best available driver and accept the trip. Returns driver_id.

    Preference order: same zone as pickup, then highest rating, then longest idle.
    SKIP LOCKED means concurrent dispatchers never block on or choose the same driver.
    """
    trip = fetch_one(conn, "SELECT id, status, pickup_zone_id FROM trips WHERE id = %s FOR UPDATE", (trip_id,))
    if trip is None:
        raise DomainError("NOT_FOUND", "trip not found")
    if trip["status"] != "requested":
        raise DomainError("TRIP_INVALID_TRANSITION", f"trip is {trip['status']}, not requested")
    # Step 1: rank candidates with a plain read. No locks are taken here, so
    # ORDER BY can scan freely. (A single FOR UPDATE ... ORDER BY ... LIMIT 1
    # would lock every row it examines before sorting and starve other
    # dispatchers, which is exactly what concurrency/dispatch.py demonstrates.)
    candidates = fetch_all(
        conn,
        """
        SELECT d.user_id, v.id AS vehicle_id
          FROM drivers d
          JOIN vehicles v ON v.driver_id = d.user_id AND v.is_active = 1
         WHERE d.status = 'available'
         ORDER BY (d.current_zone_id = %s) DESC,
                  (d.rating_sum / NULLIF(d.rating_count, 0)) DESC,
                  d.user_id
         LIMIT 10
        """,
        (trip["pickup_zone_id"],),
    )
    # Step 2: lock exactly one row. SKIP LOCKED returns nothing if another
    # dispatcher holds it, so we move to the next candidate instead of waiting.
    cand = None
    for c in candidates:
        locked = fetch_one(
            conn,
            "SELECT user_id FROM drivers WHERE user_id = %s AND status = 'available' FOR UPDATE SKIP LOCKED",
            (c["user_id"],),
        )
        if locked:
            cand = c
            break
    if cand is None:
        raise DomainError("NO_DRIVER", "no available driver")
    execute(
        conn,
        "UPDATE trips SET status = 'accepted', driver_id = %s, vehicle_id = %s WHERE id = %s",
        (cand["user_id"], cand["vehicle_id"], trip_id),
    )
    return cand["user_id"]


def start_trip(conn: MySQLConnection, trip_id: int) -> None:
    n = execute(conn, "UPDATE trips SET status = 'in_progress' WHERE id = %s", (trip_id,))
    if n == 0:
        raise DomainError("NOT_FOUND", "trip not found")


def complete_trip(conn: MySQLConnection, trip_id: int, distance_km: float) -> int:
    """Complete the trip, compute the fare from the actual distance and elapsed time."""
    trip = fetch_one(
        conn,
        "SELECT status, surge_multiplier, "
        "       GREATEST(60, TIMESTAMPDIFF(SECOND, started_at, CURRENT_TIMESTAMP(3))) AS duration_sec "
        "  FROM trips WHERE id = %s FOR UPDATE",
        (trip_id,),
    )
    if trip is None:
        raise DomainError("NOT_FOUND", "trip not found")
    if trip["status"] != "in_progress":
        raise DomainError("TRIP_INVALID_TRANSITION", f"trip is {trip['status']}, not in_progress")
    duration = int(trip["duration_sec"])
    fare = quote_cents(distance_km, duration, trip["surge_multiplier"])
    # completed_at is filled by trg_trips_bu from the database clock.
    execute(
        conn,
        "UPDATE trips SET status = 'completed', distance_km = %s, duration_sec = %s, fare_cents = %s WHERE id = %s",
        (distance_km, duration, fare, trip_id),
    )
    return fare


def cancel_trip(conn: MySQLConnection, trip_id: int, reason: str) -> None:
    n = execute(conn, "UPDATE trips SET status = 'cancelled', cancel_reason = %s WHERE id = %s", (reason, trip_id))
    if n == 0:
        raise DomainError("NOT_FOUND", "trip not found")


def get_trip(conn: MySQLConnection, trip_id: int) -> dict | None:
    return fetch_one(conn, "SELECT * FROM v_trip_detail WHERE id = %s", (trip_id,))


def trip_events(conn: MySQLConnection, trip_id: int) -> list[dict]:
    return fetch_all(
        conn,
        "SELECT from_status, to_status, occurred_at FROM trip_events WHERE trip_id = %s ORDER BY id",
        (trip_id,),
    )


# --------------------------------------------------------------------------- payments and ratings

def record_payment(conn: MySQLConnection, trip_id: int, method: str, capture: bool = True) -> int:
    trip = fetch_one(conn, "SELECT fare_cents FROM trips WHERE id = %s", (trip_id,))
    if trip is None:
        raise DomainError("NOT_FOUND", "trip not found")
    status = "captured" if capture else "pending"
    return execute(
        conn,
        "INSERT INTO payments (trip_id, amount_cents, method, status) VALUES (%s, %s, %s, %s)",
        (trip_id, trip["fare_cents"], method, status),
    )


def capture_payment(conn: MySQLConnection, trip_id: int) -> None:
    execute(conn, "UPDATE payments SET status = 'captured' WHERE trip_id = %s", (trip_id,))


def refund_payment(conn: MySQLConnection, trip_id: int) -> None:
    execute(conn, "UPDATE payments SET status = 'refunded' WHERE trip_id = %s", (trip_id,))


def rate_trip(conn: MySQLConnection, trip_id: int, rated_by: str, score: int, comment: str | None = None) -> int:
    return execute(
        conn,
        "INSERT INTO ratings (trip_id, rated_by, score, comment) VALUES (%s, %s, %s, %s)",
        (trip_id, rated_by, score, comment),
    )


def driver_profile(conn: MySQLConnection, driver_id: int) -> dict | None:
    return fetch_one(conn, "SELECT * FROM v_driver_profile WHERE user_id = %s", (driver_id,))


def rider_profile(conn: MySQLConnection, rider_id: int) -> dict | None:
    return fetch_one(conn, "SELECT * FROM v_rider_profile WHERE user_id = %s", (rider_id,))


def driver_earnings(conn: MySQLConnection, driver_id: int, days: int = 30) -> dict:
    return fetch_one(
        conn,
        """
        SELECT COUNT(*) AS trips,
               COALESCE(SUM(t.fare_cents), 0) AS gross_cents,
               COALESCE(SUM(t.distance_km), 0) AS km,
               COALESCE(SUM(t.duration_sec), 0) AS seconds
          FROM trips t
         WHERE t.driver_id = %s AND t.status = 'completed'
           AND t.completed_at >= UTC_TIMESTAMP(3) - INTERVAL %s DAY
        """,
        (driver_id, days),
    )
