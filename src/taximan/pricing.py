"""Fare computation. Pure function so it is trivially testable and the same
formula is used by the API, the data generator and the analytics checks."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

BASE_FARE_CENTS = 350
PER_KM_CENTS = 95
PER_MIN_CENTS = 25
MIN_FARE_CENTS = 600


def quote_cents(distance_km: float | Decimal, duration_sec: int, surge: float | Decimal = 1.0) -> int:
    """Return the fare in integer cents.

    fare = max(MIN, (base + per_km * km + per_min * minutes) * surge)
    Rounded half up to the cent, never floating point in the stored value.
    """
    km = Decimal(str(distance_km))
    minutes = Decimal(duration_sec) / Decimal(60)
    raw = (Decimal(BASE_FARE_CENTS) + Decimal(PER_KM_CENTS) * km + Decimal(PER_MIN_CENTS) * minutes) * Decimal(str(surge))
    cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(MIN_FARE_CENTS, cents)
