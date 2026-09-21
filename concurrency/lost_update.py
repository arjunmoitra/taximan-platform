"""Lost update on a driver's rating aggregate, reproduced and fixed.

Schedule (both transactions want to add a rating to the same driver):

    T1: r1(rating_sum)                      w1(rating_sum = old + 5)  commit
    T2:                 r2(rating_sum)                                   w2(rating_sum = old + 4)  commit

Under REPEATABLE READ both plain reads see the same snapshot. T2's write
blocks on T1's row lock until T1 commits, then overwrites T1's result with a
value computed from the stale read. One rating vanishes.

Precedence graph: r1(x) < w2(x) gives T1 -> T2, and r2(x) < w1(x) gives
T2 -> T1. A cycle, so the schedule is not conflict serializable.

Three variants are run:
  A. naive read, compute in Python, write        -> lost update (count off by one)
  B. SELECT ... FOR UPDATE, compute, write        -> correct (T2's read waits for T1)
  C. atomic UPDATE ... SET x = x + ?              -> correct (what trg_ratings_ai does)
"""
from __future__ import annotations

import time

from _lab import Timeline, cleanup_users, console, fresh_driver, run_parallel
from taximan.db import connect, execute, fetch_one, transaction


def read_modify_write(driver_id: int, delta: int, who: str, tl: Timeline, locking: bool) -> None:
    conn = connect()
    try:
        conn.start_transaction()
        sql = "SELECT rating_sum, rating_count FROM drivers WHERE user_id = %s" + (" FOR UPDATE" if locking else "")
        tl.step(who, f"BEGIN; {sql.split('FROM')[0].strip()} ... {'FOR UPDATE' if locking else '(plain read)'}")
        row = fetch_one(conn, sql, (driver_id,))
        tl.step(who, f"read sum={row['rating_sum']} count={row['rating_count']}")
        time.sleep(0.3)  # simulate application work between read and write
        new_sum, new_count = row["rating_sum"] + delta, row["rating_count"] + 1
        tl.step(who, f"UPDATE drivers SET rating_sum={new_sum}, rating_count={new_count}  (waits if row is locked)")
        execute(conn, "UPDATE drivers SET rating_sum = %s, rating_count = %s WHERE user_id = %s", (new_sum, new_count, driver_id))
        conn.commit()
        tl.step(who, "COMMIT")
    finally:
        conn.close()


def atomic_increment(driver_id: int, delta: int, who: str, tl: Timeline) -> None:
    conn = connect()
    try:
        conn.start_transaction()
        tl.step(who, f"BEGIN; UPDATE drivers SET rating_sum = rating_sum + {delta}, rating_count = rating_count + 1")
        execute(conn, "UPDATE drivers SET rating_sum = rating_sum + %s, rating_count = rating_count + 1 WHERE user_id = %s", (delta, driver_id))
        time.sleep(0.3)
        conn.commit()
        tl.step(who, "COMMIT")
    finally:
        conn.close()


def state(driver_id: int) -> tuple[int, int]:
    with transaction() as conn:
        row = fetch_one(conn, "SELECT rating_sum, rating_count FROM drivers WHERE user_id = %s", (driver_id,))
    return row["rating_sum"], row["rating_count"]


def main() -> None:
    with transaction() as conn:
        driver_id = fresh_driver(conn, "lostupdate")
        execute(conn, "UPDATE drivers SET rating_sum = 100, rating_count = 20 WHERE user_id = %s", (driver_id,))
    try:
        for label, runner in [
            ("A. naive read-modify-write", lambda who, d, tl: read_modify_write(driver_id, d, who, tl, locking=False)),
            ("B. SELECT ... FOR UPDATE",   lambda who, d, tl: read_modify_write(driver_id, d, who, tl, locking=True)),
            ("C. atomic UPDATE x = x + d",  lambda who, d, tl: atomic_increment(driver_id, d, who, tl)),
        ]:
            with transaction() as conn:
                execute(conn, "UPDATE drivers SET rating_sum = 100, rating_count = 20 WHERE user_id = %s", (driver_id,))
            tl = Timeline()
            run_parallel(lambda: runner("T1", 5, tl), lambda: runner("T2", 4, tl))
            tl.print(label)
            s, c = state(driver_id)
            expected = (109, 22)
            verdict = "[green]CORRECT[/green]" if (s, c) == expected else "[red]LOST UPDATE[/red]"
            console.print(f"final rating_sum={s} rating_count={c}   expected {expected}   {verdict}\n")
    finally:
        cleanup_users([driver_id])


if __name__ == "__main__":
    main()
