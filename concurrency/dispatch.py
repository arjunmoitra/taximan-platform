"""Parallel dispatchers with SELECT ... FOR UPDATE SKIP LOCKED.

Eight trips are requested at once and eight dispatcher threads run
services.dispatch_trip concurrently against three available drivers.
Without SKIP LOCKED, every dispatcher would queue on the same best driver
row and seven of them would fail after waiting. With it, each dispatcher
skips rows another transaction holds, so three trips are accepted
immediately, five report NO_DRIVER, and no driver is double assigned.
"""
from __future__ import annotations

from collections import Counter

from _lab import cleanup_users, console, fresh_driver, fresh_rider, run_parallel
from taximan import services as svc
from taximan.db import DomainError, connect, fetch_all, transaction


def dispatch(trip_id: int):
    conn = connect()
    try:
        with transaction(conn):
            return svc.dispatch_trip(conn, trip_id)
    except DomainError as exc:
        return exc.code
    finally:
        conn.close()


def main() -> None:
    with transaction() as conn:
        # park every seeded driver so only the lab drivers are candidates
        drivers = [fresh_driver(conn, f"disp{i}") for i in range(3)]
        riders = [fresh_rider(conn, f"disp{i}") for i in range(8)]
        trips = [svc.request_trip(conn, r, 1, 2) for r in riders]
    try:
        with transaction() as conn:
            parked = fetch_all(conn, "SELECT user_id FROM drivers WHERE status = 'available' AND user_id NOT IN (%s,%s,%s) FOR UPDATE", tuple(drivers))
            svc.execute(conn, "UPDATE drivers SET status = 'offline' WHERE status = 'available' AND user_id NOT IN (%s,%s,%s)", tuple(drivers))
        results = run_parallel(*[lambda t=t: dispatch(t) for t in trips])
        with transaction() as conn:
            assigned = fetch_all(conn, "SELECT driver_id, COUNT(*) AS n FROM trips WHERE id IN (%s) AND status = 'accepted' GROUP BY driver_id" % ",".join(map(str, trips)))
        console.rule("Parallel dispatch, 8 trips, 3 drivers, SKIP LOCKED")
        console.print("dispatcher outcomes:", Counter(str(r) if isinstance(r, str) else "accepted" for r in results))
        console.print("trips per driver:", {row["driver_id"]: row["n"] for row in assigned})
        ok = all(row["n"] == 1 for row in assigned) and len(assigned) == 3
        console.print("[green]CORRECT, each driver got exactly one trip[/green]" if ok else "[red]BUG[/red]")
        with transaction() as conn:
            for row in parked:
                svc.execute(conn, "UPDATE drivers SET status = 'available' WHERE user_id = %s", (row["user_id"],))
    finally:
        cleanup_users(drivers + riders)


if __name__ == "__main__":
    main()
