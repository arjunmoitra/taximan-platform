"""Shared helpers for the concurrency demonstrations."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from rich.console import Console

from taximan.db import connect, execute, fetch_one, transaction
from taximan import services as svc

console = Console()


@dataclass
class Timeline:
    """Collects timestamped steps from several threads to print one interleaving."""
    t0: float = field(default_factory=time.perf_counter)
    rows: list[tuple[float, str, str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def step(self, who: str, what: str) -> None:
        with self.lock:
            self.rows.append((time.perf_counter() - self.t0, who, what))

    def print(self, title: str) -> None:
        console.rule(title)
        for t, who, what in self.rows:
            console.print(f"[dim]{t*1000:7.1f} ms[/dim]  [bold]{who}[/bold]  {what}")


def fresh_driver(conn, tag: str, zone_id: int = 1, status: str = "available") -> int:
    """Create an approved, online driver with an active vehicle. Returns user_id."""
    uid = svc.create_user(conn, email=f"lab.{tag}.{time.time_ns()}@example.com",
                          phone_e164=f"+1999{time.time_ns() % 10_000_000:07d}",
                          full_name=f"Lab Driver {tag}", password="password123")
    svc.register_driver(conn, uid, licence_no=f"LAB-{time.time_ns()}", zone_id=zone_id)
    svc.approve_driver(conn, uid)
    svc.add_vehicle(conn, uid, plate=f"LAB{time.time_ns() % 1_000_000}", make="Toyota", model="Prius", model_year=2021)
    if status == "available":
        svc.set_driver_status(conn, uid, "available", zone_id)
    return uid


def fresh_rider(conn, tag: str) -> int:
    uid = svc.create_user(conn, email=f"lab.rider.{tag}.{time.time_ns()}@example.com",
                          phone_e164=f"+1998{time.time_ns() % 10_000_000:07d}",
                          full_name=f"Lab Rider {tag}", password="password123")
    svc.register_rider(conn, uid, 1)
    return uid


def cleanup_users(user_ids: list[int]) -> None:
    """Delete lab users; riders/drivers/vehicles cascade, trips are deleted first."""
    with transaction() as conn:
        for uid in user_ids:
            execute(conn, "DELETE FROM trips WHERE rider_id = %s OR driver_id = %s", (uid, uid))
        for uid in user_ids:
            execute(conn, "DELETE FROM users WHERE id = %s", (uid,))


def run_parallel(*fns) -> list:
    """Run callables in threads, start them together, return their results in order."""
    results = [None] * len(fns)
    errors = [None] * len(fns)
    barrier = threading.Barrier(len(fns))

    def wrap(i, fn):
        def run():
            barrier.wait()
            try:
                results[i] = fn()
            except Exception as exc:  # noqa: BLE001
                errors[i] = exc
        return run

    threads = [threading.Thread(target=wrap(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [e if e is not None else r for r, e in zip(results, errors)]
