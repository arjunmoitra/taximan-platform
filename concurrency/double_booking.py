"""Double booking: two trips accept the same driver at the same instant.

Schedule (both transactions dispatch to the same available driver):

    T1: r1(driver.status)='available'                w1(trip1.driver=D) w1(driver.status='on_trip') commit
    T2:                  r2(driver.status)='available'                w2(trip2.driver=D) w2(driver.status='on_trip') commit

The reads do not conflict with each other, but r1 < w2 gives T1 -> T2 and
r2 < w1 gives T2 -> T1. Cycle, not serializable, and the outcome is a driver
assigned to two trips at once.

Part 1 shows the anomaly on a scratch table with the unguarded check-then-act
pattern. Part 2 shows the same code with a locking read: exactly one wins.
Part 3 runs the real platform path (services.accept_trip, whose trigger takes
FOR UPDATE on the driver row) and proves the database rejects the second accept
with DRIVER_UNAVAILABLE.
"""
from __future__ import annotations

import time

from _lab import Timeline, cleanup_users, console, fresh_driver, fresh_rider, run_parallel
from taximan import services as svc
from taximan.db import DomainError, connect, execute, fetch_one, transaction


def scratch_accept(slot_id: int, trip: str, who: str, tl: Timeline, locking: bool) -> bool:
    conn = connect()
    try:
        conn.start_transaction()
        sql = "SELECT status FROM lab_slots WHERE driver_id = %s" + (" FOR UPDATE" if locking else "")
        tl.step(who, f"BEGIN; read driver status {'FOR UPDATE' if locking else '(plain read)'}")
        row = fetch_one(conn, sql, (slot_id,))
        tl.step(who, f"sees status={row['status']}")
        if row["status"] != "available":
            tl.step(who, "[yellow]driver busy, give up, ROLLBACK[/yellow]")
            conn.rollback()
            return False
        time.sleep(0.2)
        execute(conn, "UPDATE lab_slots SET status = 'on_trip', trip = %s WHERE driver_id = %s", (trip, slot_id))
        tl.step(who, f"UPDATE status='on_trip', trip={trip}")
        conn.commit()
        tl.step(who, "COMMIT")
        return True
    finally:
        conn.close()


def real_accept(trip_id: int, driver_id: int, who: str, tl: Timeline):
    conn = connect()
    try:
        tl.step(who, f"BEGIN; accept_trip(trip={trip_id}, driver={driver_id})")
        with transaction(conn):
            svc.accept_trip(conn, trip_id, driver_id)
            tl.step(who, "trip row updated, trigger took FOR UPDATE on driver, holding lock 0.2s")
            time.sleep(0.2)
        tl.step(who, "[green]COMMIT, accepted[/green]")
        return "accepted"
    except DomainError as exc:
        tl.step(who, f"[red]rejected by database: {exc.code}[/red]")
        return exc.code
    finally:
        conn.close()


def main() -> None:
    with transaction() as conn:
        execute(conn, "DROP TABLE IF EXISTS lab_slots")
        execute(conn, "CREATE TABLE lab_slots (driver_id INT PRIMARY KEY, status VARCHAR(16) NOT NULL, trip VARCHAR(8) NULL) ENGINE=InnoDB")
        execute(conn, "INSERT INTO lab_slots VALUES (1, 'available', NULL)")

    for label, locking in [("Part 1. unguarded check-then-act", False), ("Part 2. check-then-act with SELECT ... FOR UPDATE", True)]:
        with transaction() as conn:
            execute(conn, "UPDATE lab_slots SET status = 'available', trip = NULL WHERE driver_id = 1")
        tl = Timeline()
        wins = run_parallel(lambda: scratch_accept(1, "trip1", "T1", tl, locking),
                            lambda: scratch_accept(1, "trip2", "T2", tl, locking))
        tl.print(label)
        with transaction() as conn:
            row = fetch_one(conn, "SELECT status, trip FROM lab_slots WHERE driver_id = 1")
        n = sum(1 for w in wins if w is True)
        verdict = "[red]DOUBLE BOOKED, both transactions believe they own the driver[/red]" if n == 2 else "[green]exactly one winner[/green]"
        console.print(f"winners={n}  final row={row}   {verdict}\n")

    with transaction() as conn:
        execute(conn, "DROP TABLE lab_slots")

    # Part 3: the real thing
    with transaction() as conn:
        driver_id = fresh_driver(conn, "dbl")
        r1, r2 = fresh_rider(conn, "a"), fresh_rider(conn, "b")
        t1 = svc.request_trip(conn, r1, 1, 2)
        t2 = svc.request_trip(conn, r2, 1, 3)
    try:
        tl = Timeline()
        outcomes = run_parallel(lambda: real_accept(t1, driver_id, "T1", tl), lambda: real_accept(t2, driver_id, "T2", tl))
        tl.print("Part 3. platform path: services.accept_trip + trg_trips_bu FOR UPDATE")
        with transaction() as conn:
            assigned = fetch_one(conn, "SELECT COUNT(*) AS n FROM trips WHERE driver_id = %s AND status = 'accepted'", (driver_id,))["n"]
            dstatus = fetch_one(conn, "SELECT status FROM drivers WHERE user_id = %s", (driver_id,))["status"]
        ok = outcomes.count("accepted") == 1 and assigned == 1
        console.print(f"outcomes={outcomes}  trips assigned to driver={assigned}  driver.status={dstatus}   "
                      f"{'[green]CORRECT, one accept, one DRIVER_UNAVAILABLE[/green]' if ok else '[red]BUG[/red]'}")
    finally:
        cleanup_users([driver_id, r1, r2])


if __name__ == "__main__":
    main()
