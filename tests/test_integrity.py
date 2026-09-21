"""Whole dataset invariants on the seeded test database. The seed loads
ratings and trips with every trigger firing; here we recompute the derived
values from scratch and assert the database got them right."""
from taximan.db import fetch_one

# Other test modules commit their own trips (concurrency tests need real
# commits). Integrity checks look only at the seeded population.
SEEDED = "t.rider_id NOT IN (SELECT id FROM users WHERE email LIKE 't.%' OR email LIKE 'api.%')"


def test_driver_aggregates_match_recomputation(conn):
    row = fetch_one(conn, """
        SELECT COUNT(*) AS bad FROM drivers d
        LEFT JOIN (SELECT t.driver_id, SUM(r.score) s, COUNT(*) c FROM ratings r JOIN trips t ON t.id = r.trip_id
                    WHERE r.rated_by = 'rider' GROUP BY t.driver_id) x ON x.driver_id = d.user_id
        WHERE COALESCE(x.s, 0) <> d.rating_sum OR COALESCE(x.c, 0) <> d.rating_count""")
    assert row["bad"] == 0


def test_rider_aggregates_match_recomputation(conn):
    row = fetch_one(conn, """
        SELECT COUNT(*) AS bad FROM riders r
        LEFT JOIN (SELECT t.rider_id, SUM(x.score) s, COUNT(*) c FROM ratings x JOIN trips t ON t.id = x.trip_id
                    WHERE x.rated_by = 'driver' GROUP BY t.rider_id) y ON y.rider_id = r.user_id
        WHERE COALESCE(y.s, 0) <> r.rating_sum OR COALESCE(y.c, 0) <> r.rating_count""")
    assert row["bad"] == 0


def test_every_trip_has_an_audit_event(conn):
    row = fetch_one(conn, "SELECT COUNT(*) AS n FROM trips t LEFT JOIN trip_events e ON e.trip_id = t.id WHERE e.id IS NULL")
    assert row["n"] == 0


def test_every_completed_trip_has_exactly_one_payment_equal_to_fare(conn):
    row = fetch_one(conn, """
        SELECT SUM(p.id IS NULL) AS missing, SUM(p.amount_cents <> t.fare_cents) AS wrong
          FROM trips t LEFT JOIN payments p ON p.trip_id = t.id WHERE t.status = 'completed' AND """ + SEEDED)
    assert row["missing"] == 0 and row["wrong"] == 0


def test_no_driver_has_overlapping_trips(conn):
    row = fetch_one(conn, """
        SELECT COUNT(*) AS n FROM trips a JOIN trips b
          ON a.driver_id = b.driver_id AND a.id < b.id
         AND a.status = 'completed' AND b.status = 'completed'
         AND b.accepted_at < a.completed_at AND a.accepted_at < b.completed_at""")
    assert row["n"] == 0


def test_on_trip_drivers_have_an_in_flight_trip(conn):
    row = fetch_one(conn, """
        SELECT COUNT(*) AS n FROM drivers d WHERE d.status = 'on_trip'
           AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.driver_id = d.user_id AND t.status IN ('accepted', 'in_progress'))""")
    assert row["n"] == 0


def test_seed_volume(conn):
    row = fetch_one(conn, "SELECT (SELECT COUNT(*) FROM trips) AS trips, (SELECT COUNT(*) FROM drivers) AS drivers")
    assert row["trips"] >= 5000 and row["drivers"] >= 40
