"""Prove the warehouse copy matches the source.

Every check is a plain aggregate (COUNT, SUM, MIN, MAX) that means the same
thing in MySQL, Snowflake and DuckDB, compared exactly in Python. A column that
loaded as the wrong type, was truncated, or lost its time zone changes at least
one of these numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

CHECKS: dict[str, tuple[str, ...]] = {
    "zones":       ("COUNT(*)", "SUM(id)"),
    "riders":      ("COUNT(*)", "SUM(rating_sum)", "SUM(rating_count)", "MIN(created_at)", "MAX(created_at)"),
    "drivers":     ("COUNT(*)", "SUM(rating_sum)", "SUM(rating_count)", "MIN(created_at)", "MAX(created_at)", "MAX(approved_at)"),
    "vehicles":    ("COUNT(*)", "SUM(model_year)", "SUM(seats)", "MIN(created_at)", "MAX(created_at)"),
    "trips":       ("COUNT(*)", "SUM(fare_cents)", "SUM(distance_km)", "SUM(duration_sec)", "SUM(surge_multiplier)",
                    "MIN(requested_at)", "MAX(requested_at)", "MAX(completed_at)"),
    "trip_events": ("COUNT(*)", "MIN(occurred_at)", "MAX(occurred_at)"),
    "payments":    ("COUNT(*)", "SUM(amount_cents)", "MIN(captured_at)", "MAX(captured_at)"),
    "ratings":     ("COUNT(*)", "SUM(score)", "MIN(created_at)", "MAX(created_at)"),
}

# A function that runs one SQL string and returns the first row.
RunOne = Callable[[str], tuple]


@dataclass(frozen=True)
class Check:
    table: str
    expression: str
    source: object
    target: object

    @property
    def ok(self) -> bool:
        return self.source == self.target


def _normalise(value: object) -> object:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    return value


def reconcile(source: RunOne, target: RunOne, target_prefix: str = "raw.") -> list[Check]:
    results: list[Check] = []
    for table, expressions in CHECKS.items():
        select = ", ".join(expressions)
        src_row = source(f"SELECT {select} FROM {table}")
        tgt_row = target(f"SELECT {select} FROM {target_prefix}{table}")
        for expr, s, t in zip(expressions, src_row, tgt_row):
            results.append(Check(table, expr, _normalise(s), _normalise(t)))
    return results
