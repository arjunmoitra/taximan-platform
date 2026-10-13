"""What leaves MySQL, column by column.

This is an allowlist. A column that is not listed here is never selected, so
personal data (email, phone, password hash, full name, licence number, plate,
free text rating comments) cannot reach the warehouse by accident when someone
later adds a column to the OLTP schema. `warehouse/snowflake/02_raw_tables.sql`
must declare the same columns in the same order, and a test enforces that.
"""
from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

INT32 = pa.int32()
INT64 = pa.int64()
STR = pa.string()
BOOL = pa.bool_()
TS = pa.timestamp("ms")  # DATETIME(3) in MySQL


def dec(precision: int, scale: int) -> pa.DataType:
    return pa.decimal128(precision, scale)


@dataclass(frozen=True)
class Column:
    name: str
    arrow: pa.DataType


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[Column, ...]
    order_by: str  # primary key, so extracts are reproducible

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def schema(self) -> pa.Schema:
        return pa.schema([pa.field(c.name, c.arrow) for c in self.columns])

    @property
    def select_sql(self) -> str:
        cols = ", ".join(f"`{c.name}`" for c in self.columns)
        return f"SELECT {cols} FROM `{self.name}` ORDER BY `{self.order_by}`"


def _t(name: str, order_by: str, *cols: tuple[str, pa.DataType]) -> TableSpec:
    return TableSpec(name, tuple(Column(n, t) for n, t in cols), order_by)


TABLES: tuple[TableSpec, ...] = (
    _t("zones", "id",
       ("id", INT32), ("city", STR), ("name", STR),
       ("centroid_lat", dec(9, 6)), ("centroid_lng", dec(9, 6))),
    _t("riders", "user_id",
       ("user_id", INT64), ("home_zone_id", INT32), ("rating_sum", INT64),
       ("rating_count", INT64), ("created_at", TS)),
    _t("drivers", "user_id",
       ("user_id", INT64), ("status", STR), ("current_zone_id", INT32),
       ("rating_sum", INT64), ("rating_count", INT64),
       ("approved_at", TS), ("created_at", TS)),
    _t("vehicles", "id",
       ("id", INT64), ("driver_id", INT64), ("make", STR), ("model", STR),
       ("model_year", INT32), ("seats", INT32), ("is_active", BOOL), ("created_at", TS)),
    _t("trips", "id",
       ("id", INT64), ("rider_id", INT64), ("driver_id", INT64), ("vehicle_id", INT64),
       ("pickup_zone_id", INT32), ("dropoff_zone_id", INT32), ("status", STR),
       ("requested_at", TS), ("accepted_at", TS), ("started_at", TS),
       ("completed_at", TS), ("cancelled_at", TS), ("cancel_reason", STR),
       ("distance_km", dec(6, 2)), ("duration_sec", INT64),
       ("surge_multiplier", dec(3, 2)), ("fare_cents", INT64)),
    _t("trip_events", "id",
       ("id", INT64), ("trip_id", INT64), ("from_status", STR),
       ("to_status", STR), ("occurred_at", TS)),
    _t("payments", "id",
       ("id", INT64), ("trip_id", INT64), ("amount_cents", INT64), ("method", STR),
       ("status", STR), ("captured_at", TS), ("created_at", TS)),
    _t("ratings", "id",
       ("id", INT64), ("trip_id", INT64), ("rated_by", STR),
       ("score", INT32), ("created_at", TS)),
)

BY_NAME = {t.name: t for t in TABLES}

# Column names that must never appear in the warehouse, in any table. The test
# suite checks the allowlist, the RAW DDL and every extracted Parquet schema.
FORBIDDEN_COLUMNS = frozenset({
    "email", "phone_e164", "full_name", "password_hash", "licence_no", "plate", "comment",
})
