"""Scenario builders shared by the analytics and warehouse tests."""
from __future__ import annotations

from datetime import datetime, timedelta


def make_rating_drop(conn, base: datetime = datetime(2026, 1, 1)) -> int:
    """Give one driver a clear drop in rider ratings and return their id.

    Q11 flags a driver whose last 20 rider ratings average at least 0.5 below the
    20 before. In the seed that happens only by chance, and the seed changes with
    the date, so tests that need it build it: the 20 older ratings become 5s and
    the 20 newer ones 3s, a drop of exactly 2.00. Ratings are immutable by trigger,
    so this deletes and re-inserts them, which keeps the driver's aggregates right.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT t.driver_id FROM ratings r JOIN trips t ON t.id = r.trip_id "
            "WHERE r.rated_by = 'rider' GROUP BY t.driver_id HAVING COUNT(*) >= 40 "
            "ORDER BY t.driver_id LIMIT 1"
        )
        row = cur.fetchone()
        assert row, "the seed has no driver with 40 rider ratings"
        driver_id = row[0]
        cur.execute(
            "SELECT r.id, r.trip_id FROM ratings r JOIN trips t ON t.id = r.trip_id "
            "WHERE t.driver_id = %s AND r.rated_by = 'rider' ORDER BY r.id",
            (driver_id,),
        )
        rated = cur.fetchall()
        cur.execute(
            "DELETE r FROM ratings r JOIN trips t ON t.id = r.trip_id "
            "WHERE t.driver_id = %s AND r.rated_by = 'rider'",
            (driver_id,),
        )
        for i, (_, trip_id) in enumerate(rated[:40]):
            score = 5 if i < 20 else 3
            cur.execute(
                "INSERT INTO ratings (trip_id, rated_by, score, created_at) VALUES (%s, 'rider', %s, %s)",
                (trip_id, score, base + timedelta(minutes=i)),
            )
        return driver_id
    finally:
        cur.close()
