"""Two real connections racing. Each test proves the database, not the test,
serialised the outcome."""
import threading

from taximan import services as svc
from taximan.db import DomainError, connect, fetch_one, transaction


def _race(*fns):
    results = [None] * len(fns)
    barrier = threading.Barrier(len(fns))

    def run(i, fn):
        barrier.wait()
        try:
            results[i] = fn()
        except DomainError as exc:
            results[i] = exc.code

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


def test_double_booking_is_rejected(make_driver, make_rider):
    with transaction() as c:
        d = make_driver(c)
        t1 = svc.request_trip(c, make_rider(c), 1, 2)
        t2 = svc.request_trip(c, make_rider(c), 1, 3)

    def accept(t):
        conn = connect()
        try:
            with transaction(conn):
                svc.accept_trip(conn, t, d)
            return "accepted"
        finally:
            conn.close()

    outcomes = _race(lambda: accept(t1), lambda: accept(t2))
    assert sorted(outcomes) == ["DRIVER_UNAVAILABLE", "accepted"]
    with transaction() as c:
        n = fetch_one(c, "SELECT COUNT(*) AS n FROM trips WHERE driver_id = %s AND status = 'accepted'", (d,))["n"]
    assert n == 1


def test_concurrent_ratings_are_not_lost(make_driver, make_rider):
    """Ten trips rated at the same instant by ten connections: the trigger's
    atomic increment must count all ten."""
    with transaction() as c:
        d = make_driver(c)
        trips = []
        for _ in range(10):
            t = svc.request_trip(c, make_rider(c), 1, 2)
            svc.accept_trip(c, t, d)
            svc.start_trip(c, t)
            svc.complete_trip(c, t, 2.0)
            trips.append(t)

    def rate(t):
        conn = connect()
        try:
            with transaction(conn):
                svc.rate_trip(conn, t, "rider", 4)
            return "ok"
        finally:
            conn.close()

    outcomes = _race(*[lambda t=t: rate(t) for t in trips])
    assert outcomes == ["ok"] * 10
    with transaction() as c:
        prof = svc.driver_profile(c, d)
    assert prof["rating_count"] == 10 and float(prof["rating_avg"]) == 4.0


def test_parallel_dispatch_never_double_assigns(make_driver, make_rider):
    with transaction() as c:
        # only our drivers are available during this test
        c.cursor().execute("UPDATE drivers SET status = 'offline' WHERE status = 'available'")
        drivers = [make_driver(c) for _ in range(3)]
        trips = [svc.request_trip(c, make_rider(c), 1, 2) for _ in range(6)]

    def dispatch(t):
        conn = connect()
        try:
            with transaction(conn):
                return svc.dispatch_trip(conn, t)
        finally:
            conn.close()

    outcomes = _race(*[lambda t=t: dispatch(t) for t in trips])
    assigned = [o for o in outcomes if isinstance(o, int)]
    assert sorted(assigned) == sorted(drivers), outcomes
    assert outcomes.count("NO_DRIVER") == 3
