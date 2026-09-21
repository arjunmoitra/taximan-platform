"""Synthetic data generator.

Produces a year of ride hailing activity for Montreal that is realistic enough
for the analytical queries to say something: hour of day and day of week demand
curves, surge that follows demand, power law rider activity, drivers that are
never double booked in the generated history, skewed ratings, and a payment
for every completed trip.

Pipeline: numpy arrays -> CSV files in data/ -> LOAD DATA LOCAL INFILE in
foreign key order. Every trigger fires during the load, so trip_events and the
rating aggregates are built by the database, not by this script. That is
deliberate: tests/test_integrity.py recomputes them from scratch and asserts
equality.
"""
from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from faker import Faker

from .config import DATA_DIR
from .db import connect, execute
from .pricing import quote_cents

# One bcrypt hash of the string "password" shared by all seed users. Hashing
# 25k passwords at cost 12 would take minutes and prove nothing.
SEED_PASSWORD_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO5Zg6xk1u9c9kZ1w0Q2uJx2Wm2p3d2e6"

ZONES = [
    ("Montreal", "Downtown", 45.5017, -73.5673, 3.0),
    ("Montreal", "Plateau", 45.5225, -73.5817, 2.0),
    ("Montreal", "Old Port", 45.5075, -73.5540, 1.6),
    ("Montreal", "Mile End", 45.5240, -73.6010, 1.2),
    ("Montreal", "Griffintown", 45.4930, -73.5620, 1.1),
    ("Montreal", "Westmount", 45.4830, -73.5980, 0.7),
    ("Montreal", "NDG", 45.4720, -73.6180, 0.9),
    ("Montreal", "Rosemont", 45.5470, -73.5850, 0.9),
    ("Montreal", "Villeray", 45.5430, -73.6170, 0.6),
    ("Montreal", "Verdun", 45.4580, -73.5680, 0.7),
    ("Montreal", "Hochelaga", 45.5390, -73.5400, 0.6),
    ("Montreal", "Airport YUL", 45.4700, -73.7400, 1.4),
]

MAKES = [("Toyota", ["Corolla", "Camry", "Prius", "RAV4"]), ("Honda", ["Civic", "Accord", "CR-V"]),
         ("Hyundai", ["Elantra", "Sonata", "Tucson"]), ("Kia", ["Forte", "Soul", "Sportage"]),
         ("Tesla", ["Model 3", "Model Y"]), ("Nissan", ["Sentra", "Altima", "Rogue"]),
         ("Chevrolet", ["Malibu", "Equinox"]), ("Volkswagen", ["Jetta", "Tiguan"])]

# hour of day demand weights (index 0..23), roughly two commute peaks and a night out bump
HOUR_W = np.array([0.35, 0.22, 0.15, 0.10, 0.10, 0.18, 0.45, 0.90, 1.20, 0.95, 0.75, 0.80,
                   0.90, 0.85, 0.85, 0.95, 1.10, 1.35, 1.30, 1.00, 0.85, 0.80, 0.75, 0.55])
# Monday .. Sunday
DOW_W = np.array([0.90, 0.92, 0.95, 1.00, 1.20, 1.25, 0.95])


@dataclass
class Counts:
    zones: int
    users: int
    riders: int
    drivers: int
    vehicles: int
    trips: int
    payments: int
    ratings: int


def _fmt(dt: datetime | None) -> str:
    return "\\N" if dt is None else dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lng2 - lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def generate(scale: float = 1.0, seed: int = 42, days: int = 365, out_dir: Path = DATA_DIR,
             now: datetime | None = None) -> Counts:
    """Write CSV files for every table. scale=1 is about 20k riders, 2.5k drivers, 300k trips."""
    rng = np.random.default_rng(seed)
    fake = Faker("en_CA")
    Faker.seed(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    n_riders = int(20_000 * scale)
    n_drivers = int(2_500 * scale)
    n_trips = int(300_000 * scale)

    # ------------------------------------------------------------------ zones
    zone_ids = np.arange(1, len(ZONES) + 1)
    zone_lat = np.array([z[2] for z in ZONES])
    zone_lng = np.array([z[3] for z in ZONES])
    zone_w = np.array([z[4] for z in ZONES])
    zone_w = zone_w / zone_w.sum()
    with open(out_dir / "zones.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "city", "name", "centroid_lat", "centroid_lng"])
        for zid, (city, name, lat, lng, _) in zip(zone_ids, ZONES):
            w.writerow([zid, city, name, lat, lng])

    # ------------------------------------------------------------------ users, riders, drivers
    n_users = n_riders + n_drivers
    user_ids = np.arange(1, n_users + 1)
    rider_ids = user_ids[:n_riders]
    driver_ids = user_ids[n_riders:]
    signup_offsets = rng.integers(0, days * 86400 * 2, size=n_users)  # up to two years ago
    signup = np.array([now - timedelta(seconds=int(s)) for s in signup_offsets])

    with open(out_dir / "users.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "email", "phone_e164", "full_name", "password_hash", "created_at"])
        for uid in user_ids:
            name = fake.name()
            local = name.lower().replace(" ", ".").replace("'", "")
            w.writerow([uid, f"{local}.{uid}@example.com", f"+1514{uid:07d}", name, SEED_PASSWORD_HASH, _fmt(signup[uid - 1])])

    rider_home = rng.choice(zone_ids, size=n_riders, p=zone_w)
    with open(out_dir / "riders.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["user_id", "home_zone_id", "created_at"])
        for uid, hz in zip(rider_ids, rider_home):
            w.writerow([uid, hz, _fmt(signup[uid - 1])])

    driver_zone = rng.choice(zone_ids, size=n_drivers, p=zone_w)
    # activity weight: a minority of full time drivers do most trips
    driver_activity = rng.pareto(2.0, size=n_drivers) + 0.2
    driver_activity /= driver_activity.sum()

    # ------------------------------------------------------------------ vehicles
    vehicle_rows = []
    active_vehicle_of = {}
    vid = 1
    for i, did in enumerate(driver_ids):
        n_veh = 2 if rng.random() < 0.08 else 1
        for k in range(n_veh):
            make, models = MAKES[rng.integers(len(MAKES))]
            model = models[rng.integers(len(models))]
            plate = f"{fake.random_uppercase_letter()}{fake.random_uppercase_letter()}{fake.random_uppercase_letter()}{rng.integers(100, 999)}"
            is_active = 1 if k == n_veh - 1 else 0
            vehicle_rows.append([vid, did, f"{plate}{vid}", make, model, int(rng.integers(2012, 2026)), int(rng.choice([4, 4, 4, 5, 6])), is_active,
                                 _fmt(signup[did - 1] + timedelta(days=int(rng.integers(0, 30))))])
            if is_active:
                active_vehicle_of[did] = vid
            vid += 1
    with open(out_dir / "vehicles.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "driver_id", "plate", "make", "model", "model_year", "seats", "is_active", "created_at"])
        w.writerows(vehicle_rows)

    # ------------------------------------------------------------------ trips
    start = now - timedelta(days=days)
    day_idx = np.arange(days)
    day_dates = [start + timedelta(days=int(d)) for d in day_idx]
    dow_w = np.array([DOW_W[d.weekday()] for d in day_dates])
    season = 1.0 + 0.15 * np.cos(2 * np.pi * (day_idx - 200) / 365.0)  # summer high, Feb low
    growth = np.linspace(0.8, 1.2, days)  # business grows through the year
    day_w = dow_w * season * growth
    day_w /= day_w.sum()
    hour_w = HOUR_W / HOUR_W.sum()

    t_day = rng.choice(day_idx, size=n_trips, p=day_w)
    t_hour = rng.choice(24, size=n_trips, p=hour_w)
    t_sec = rng.integers(0, 3600, size=n_trips)
    req_offset = t_day * 86400 + t_hour * 3600 + t_sec
    order = np.argsort(req_offset)
    req_offset = req_offset[order]
    t_hour = t_hour[order]
    t_day = t_day[order]
    requested = np.array([start + timedelta(seconds=int(s)) for s in req_offset])

    # riders: Zipf like activity
    rider_w = rng.pareto(1.5, size=n_riders) + 0.05
    rider_w /= rider_w.sum()
    t_rider = rng.choice(rider_ids, size=n_trips, p=rider_w)

    pickup = rng.choice(zone_ids, size=n_trips, p=zone_w)
    dropoff = rng.choice(zone_ids, size=n_trips, p=zone_w)
    same = dropoff == pickup
    dropoff[same] = rng.choice(zone_ids, size=same.sum(), p=zone_w)  # second draw, a few remain same zone
    base_km = _haversine_km(zone_lat[pickup - 1], zone_lng[pickup - 1], zone_lat[dropoff - 1], zone_lng[dropoff - 1])
    distance = np.round(np.maximum(0.8, base_km * 1.3 + rng.lognormal(0.3, 0.5, size=n_trips)), 2)
    speed_kmh = np.where(np.isin(t_hour, [7, 8, 9, 16, 17, 18]), 17.0, np.where(t_hour < 6, 34.0, 24.0))
    duration = (distance / speed_kmh * 3600 + rng.normal(150, 60, size=n_trips)).clip(120, None).astype(int)

    # surge follows relative demand for that hour and day, with noise
    demand_factor = (HOUR_W[t_hour] / HOUR_W.mean()) * (day_w[t_day] * days)
    surge = np.ones(n_trips)
    hot = demand_factor > 1.25
    surge[hot] = np.round(np.clip(1.0 + (demand_factor[hot] - 1.0) * rng.uniform(0.6, 1.4, size=hot.sum()), 1.0, 3.0) * 4) / 4
    surge = np.clip(surge, 1.0, 5.0)

    accept_delay = rng.exponential(75, size=n_trips).astype(int) + 5
    arrive_delay = rng.exponential(240, size=n_trips).astype(int) + 30

    # status mix. Trips in the last 90 minutes may still be in flight.
    age_sec = (now - start).total_seconds() - req_offset
    status = np.full(n_trips, "completed", dtype=object)
    cancel_roll = rng.random(n_trips)
    status[cancel_roll < 0.11] = "cancelled"
    recent = age_sec < 5400
    r = rng.random(n_trips)
    status[recent & (r < 0.35)] = "requested"
    status[recent & (r >= 0.35) & (r < 0.55)] = "accepted"
    status[recent & (r >= 0.55) & (r < 0.80)] = "in_progress"
    # anything "in flight" must be young enough to be plausible
    status[(age_sec > 5400) & np.isin(status, ["requested", "accepted", "in_progress"])] = "completed"

    cancel_reason = np.full(n_trips, None, dtype=object)
    is_cancel = status == "cancelled"
    cancel_reason[is_cancel] = rng.choice(["rider", "driver", "no_driver", "system"], size=is_cancel.sum(), p=[0.55, 0.22, 0.18, 0.05])
    cancel_after_accept = is_cancel & np.isin(cancel_reason, ["driver", "system"]) | (is_cancel & (cancel_reason == "rider") & (rng.random(n_trips) < 0.4))

    needs_driver = np.isin(status, ["completed", "accepted", "in_progress"]) | cancel_after_accept

    # greedy assignment so no driver is on two trips at once in the generated history
    busy_until = np.zeros(n_drivers)  # seconds since start
    trip_driver = np.zeros(n_trips, dtype=np.int64)
    cand_pool = rng.choice(n_drivers, size=(n_trips, 6), p=driver_activity)
    for i in range(n_trips):
        if not needs_driver[i]:
            continue
        t0 = req_offset[i]
        chosen = -1
        for c in cand_pool[i]:
            if busy_until[c] <= t0:
                chosen = c
                break
        if chosen < 0:
            chosen = int(np.argmin(busy_until))
        trip_driver[i] = driver_ids[chosen]
        end = t0 + accept_delay[i] + arrive_delay[i] + (duration[i] if status[i] in ("completed", "in_progress") else 60)
        busy_until[chosen] = end + 120

    fares = np.zeros(n_trips, dtype=np.int64)
    completed = status == "completed"
    for i in np.flatnonzero(completed):
        fares[i] = quote_cents(float(distance[i]), int(duration[i]), float(surge[i]))

    trip_ids = np.arange(1, n_trips + 1)
    with open(out_dir / "trips.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "rider_id", "driver_id", "vehicle_id", "pickup_zone_id", "dropoff_zone_id", "status",
                    "requested_at", "accepted_at", "started_at", "completed_at", "cancelled_at", "cancel_reason",
                    "distance_km", "duration_sec", "surge_multiplier", "fare_cents"])
        for i in range(n_trips):
            st = status[i]
            rq = requested[i]
            has_driver = needs_driver[i]
            did = int(trip_driver[i]) if has_driver else None
            vid_ = active_vehicle_of[did] if has_driver else None
            acc = rq + timedelta(seconds=int(accept_delay[i])) if has_driver else None
            sta = acc + timedelta(seconds=int(arrive_delay[i])) if st in ("in_progress", "completed") else None
            comp = sta + timedelta(seconds=int(duration[i])) if st == "completed" else None
            canc = None
            if st == "cancelled":
                canc = (acc + timedelta(seconds=int(rng.integers(30, 600)))) if has_driver else rq + timedelta(seconds=int(rng.integers(20, 900)))
            w.writerow([
                trip_ids[i], t_rider[i], did if did else "\\N", vid_ if vid_ else "\\N", pickup[i], dropoff[i], st,
                _fmt(rq), _fmt(acc), _fmt(sta), _fmt(comp), _fmt(canc), cancel_reason[i] or "\\N",
                distance[i] if st == "completed" else "\\N",
                duration[i] if st == "completed" else "\\N",
                f"{surge[i]:.2f}",
                fares[i] if st == "completed" else "\\N",
            ])

    # driver status consistent with in flight trips
    on_trip = set(int(trip_driver[i]) for i in np.flatnonzero(np.isin(status, ["accepted", "in_progress"])))
    with open(out_dir / "drivers.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["user_id", "licence_no", "status", "current_zone_id", "approved_at", "created_at"])
        for i, did in enumerate(driver_ids):
            if int(did) in on_trip:
                st = "on_trip"
            else:
                st = "available" if rng.random() < 0.55 else "offline"
            w.writerow([did, f"QC-{did:06d}", st, driver_zone[i], _fmt(signup[did - 1] + timedelta(days=3)), _fmt(signup[did - 1])])

    # ------------------------------------------------------------------ payments and ratings
    n_pay = 0
    with open(out_dir / "payments.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["trip_id", "amount_cents", "method", "status", "captured_at", "created_at"])
        comp_idx = np.flatnonzero(completed)
        methods = rng.choice(["card", "wallet", "cash"], size=len(comp_idx), p=[0.70, 0.22, 0.08])
        pstat = rng.choice(["captured", "pending", "refunded"], size=len(comp_idx), p=[0.97, 0.02, 0.01])
        for j, i in enumerate(comp_idx):
            comp_at = requested[i] + timedelta(seconds=int(accept_delay[i] + arrive_delay[i] + duration[i]))
            cap = comp_at + timedelta(seconds=int(rng.integers(1, 20))) if pstat[j] != "pending" else None
            w.writerow([trip_ids[i], fares[i], methods[j], pstat[j], _fmt(cap), _fmt(comp_at)])
            n_pay += 1

    n_rat = 0
    score_p = [0.02, 0.02, 0.06, 0.20, 0.70]
    with open(out_dir / "ratings.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["trip_id", "rated_by", "score", "comment", "created_at"])
        for i in comp_idx:
            comp_at = requested[i] + timedelta(seconds=int(accept_delay[i] + arrive_delay[i] + duration[i]))
            if rng.random() < 0.65:
                w.writerow([trip_ids[i], "rider", int(rng.choice([1, 2, 3, 4, 5], p=score_p)), "\\N",
                            _fmt(comp_at + timedelta(seconds=int(rng.exponential(3600))))])
                n_rat += 1
            if rng.random() < 0.40:
                w.writerow([trip_ids[i], "driver", int(rng.choice([1, 2, 3, 4, 5], p=[0.01, 0.02, 0.05, 0.17, 0.75])), "\\N",
                            _fmt(comp_at + timedelta(seconds=int(rng.exponential(900))))])
                n_rat += 1

    return Counts(len(ZONES), n_users, n_riders, n_drivers, len(vehicle_rows), n_trips, n_pay, n_rat)


LOAD_ORDER = [
    ("zones", ["id", "city", "name", "centroid_lat", "centroid_lng"]),
    ("users", ["id", "email", "phone_e164", "full_name", "password_hash", "created_at"]),
    ("riders", ["user_id", "home_zone_id", "created_at"]),
    ("drivers", ["user_id", "licence_no", "status", "current_zone_id", "approved_at", "created_at"]),
    ("vehicles", ["id", "driver_id", "plate", "make", "model", "model_year", "seats", "is_active", "created_at"]),
    ("trips", ["id", "rider_id", "driver_id", "vehicle_id", "pickup_zone_id", "dropoff_zone_id", "status",
               "requested_at", "accepted_at", "started_at", "completed_at", "cancelled_at", "cancel_reason",
               "distance_km", "duration_sec", "surge_multiplier", "fare_cents"]),
    ("payments", ["trip_id", "amount_cents", "method", "status", "captured_at", "created_at"]),
    ("ratings", ["trip_id", "rated_by", "score", "comment", "created_at"]),
]


def reset(conn) -> None:
    """Empty every domain table. Child tables first so FKs never complain."""
    for table in ["ratings", "payments", "trip_events", "trips", "vehicles", "drivers", "riders", "users", "zones"]:
        execute(conn, f"DELETE FROM {table}")
        execute(conn, f"ALTER TABLE {table} AUTO_INCREMENT = 1")
    conn.commit()


def load(data_dir: Path = DATA_DIR, conn=None, verbose: bool = True) -> dict[str, float]:
    """LOAD DATA LOCAL INFILE every CSV in FK order. Returns seconds per table."""
    owned = conn is None
    conn = conn or connect()
    timings: dict[str, float] = {}
    try:
        cur = conn.cursor()
        for table, cols in LOAD_ORDER:
            path = (data_dir / f"{table}.csv").resolve()
            t0 = time.perf_counter()
            cur.execute(
                f"LOAD DATA LOCAL INFILE '{path.as_posix()}' INTO TABLE {table} "
                f"FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' LINES TERMINATED BY '\\n' "
                f"IGNORE 1 LINES ({', '.join(cols)})"
            )
            conn.commit()
            timings[table] = time.perf_counter() - t0
            if verbose:
                print(f"  loaded {table:10s} {cur.rowcount:>8,d} rows in {timings[table]:6.1f}s")
        cur.close()
        return timings
    finally:
        if owned:
            conn.close()
