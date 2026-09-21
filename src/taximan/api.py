"""HTTP service over the domain layer.

Every handler opens one transaction, calls one or more service functions, and
returns. Business rule rejections raised by MySQL triggers arrive as
DomainError and are mapped to HTTP status codes below; the API never has to
re-implement a rule the database already enforces.

Authentication is intentionally out of scope for this repository. The
verify_password service exists so a JWT layer can be added without touching
the data model.
"""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from . import services as svc
from .analytics import list_queries, run_query
from .config import ANALYTICS_DIR
from .db import DomainError, connect, fetch_one, transaction

app = FastAPI(title="Taximan", version="1.0.0", description="Ride hailing data platform API")

_STATUS_FOR_CODE = {
    "NOT_FOUND": 404,
    "CHECK_VIOLATION": 422,
    "FK_VIOLATION": 422,
    "BAD_STATUS": 422,
}


@app.exception_handler(DomainError)
async def domain_error_handler(_, exc: DomainError):
    status = _STATUS_FOR_CODE.get(exc.code, 409)
    return JSONResponse(status_code=status, content={"error": exc.code, "detail": exc.message})


# --------------------------------------------------------------------------- schemas

class UserIn(BaseModel):
    email: EmailStr
    phone_e164: str = Field(pattern=r"^\+[1-9][0-9]{6,14}$")
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class RiderIn(BaseModel):
    user_id: int
    home_zone_id: int | None = None


class DriverIn(BaseModel):
    user_id: int
    licence_no: str = Field(min_length=3, max_length=32)
    zone_id: int | None = None


class DriverStatusIn(BaseModel):
    status: Literal["offline", "available"]
    zone_id: int | None = None


class VehicleIn(BaseModel):
    plate: str = Field(min_length=2, max_length=16)
    make: str
    model: str
    model_year: int = Field(ge=1990, le=2100)
    seats: int = Field(default=4, ge=1, le=8)


class TripIn(BaseModel):
    rider_id: int
    pickup_zone_id: int
    dropoff_zone_id: int
    surge_multiplier: float = Field(default=1.0, ge=1.0, le=5.0)


class AcceptIn(BaseModel):
    driver_id: int


class CompleteIn(BaseModel):
    distance_km: float = Field(gt=0, le=9999)


class CancelIn(BaseModel):
    reason: Literal["rider", "driver", "no_driver", "system"]


class PaymentIn(BaseModel):
    method: Literal["card", "cash", "wallet"]
    capture: bool = True


class RatingIn(BaseModel):
    rated_by: Literal["rider", "driver"]
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- routes

@app.get("/healthz")
def healthz():
    conn = connect()
    try:
        row = fetch_one(conn, "SELECT 1 AS ok")
        return {"status": "ok", "db": row["ok"] == 1}
    finally:
        conn.close()


@app.post("/users", status_code=201)
def create_user(body: UserIn):
    with transaction() as conn:
        uid = svc.create_user(conn, email=body.email, phone_e164=body.phone_e164,
                              full_name=body.full_name, password=body.password)
    return {"id": uid}


@app.post("/riders", status_code=201)
def create_rider(body: RiderIn):
    with transaction() as conn:
        svc.register_rider(conn, body.user_id, body.home_zone_id)
    return {"user_id": body.user_id}


@app.get("/riders/{rider_id}")
def get_rider(rider_id: int):
    with transaction() as conn:
        row = svc.rider_profile(conn, rider_id)
    if row is None:
        raise HTTPException(404, "rider not found")
    return row


@app.post("/drivers", status_code=201)
def create_driver(body: DriverIn):
    with transaction() as conn:
        svc.register_driver(conn, body.user_id, body.licence_no, body.zone_id)
    return {"user_id": body.user_id}


@app.post("/drivers/{driver_id}/approve")
def approve_driver(driver_id: int):
    with transaction() as conn:
        svc.approve_driver(conn, driver_id)
    return {"user_id": driver_id, "approved": True}


@app.put("/drivers/{driver_id}/status")
def set_driver_status(driver_id: int, body: DriverStatusIn):
    with transaction() as conn:
        svc.set_driver_status(conn, driver_id, body.status, body.zone_id)
        row = svc.driver_profile(conn, driver_id)
    return row


@app.post("/drivers/{driver_id}/vehicles", status_code=201)
def add_vehicle(driver_id: int, body: VehicleIn):
    with transaction() as conn:
        vid = svc.add_vehicle(conn, driver_id, plate=body.plate, make=body.make, model=body.model,
                              model_year=body.model_year, seats=body.seats)
    return {"id": vid}


@app.get("/drivers/{driver_id}")
def get_driver(driver_id: int):
    with transaction() as conn:
        row = svc.driver_profile(conn, driver_id)
    if row is None:
        raise HTTPException(404, "driver not found")
    return row


@app.get("/drivers/{driver_id}/earnings")
def driver_earnings(driver_id: int, days: int = Query(default=30, ge=1, le=365)):
    with transaction() as conn:
        if svc.driver_profile(conn, driver_id) is None:
            raise HTTPException(404, "driver not found")
        row = svc.driver_earnings(conn, driver_id, days)
    return {"driver_id": driver_id, "days": days, **row}


@app.post("/trips", status_code=201)
def request_trip(body: TripIn):
    with transaction() as conn:
        tid = svc.request_trip(conn, body.rider_id, body.pickup_zone_id, body.dropoff_zone_id, body.surge_multiplier)
        trip = svc.get_trip(conn, tid)
    return trip


@app.get("/trips/{trip_id}")
def get_trip(trip_id: int):
    with transaction() as conn:
        trip = svc.get_trip(conn, trip_id)
    if trip is None:
        raise HTTPException(404, "trip not found")
    return trip


@app.get("/trips/{trip_id}/events")
def get_trip_events(trip_id: int):
    with transaction() as conn:
        return svc.trip_events(conn, trip_id)


@app.post("/trips/{trip_id}/dispatch")
def dispatch(trip_id: int):
    with transaction() as conn:
        driver_id = svc.dispatch_trip(conn, trip_id)
        trip = svc.get_trip(conn, trip_id)
    return {"driver_id": driver_id, **trip}


@app.post("/trips/{trip_id}/accept")
def accept(trip_id: int, body: AcceptIn):
    with transaction() as conn:
        svc.accept_trip(conn, trip_id, body.driver_id)
        return svc.get_trip(conn, trip_id)


@app.post("/trips/{trip_id}/start")
def start(trip_id: int):
    with transaction() as conn:
        svc.start_trip(conn, trip_id)
        return svc.get_trip(conn, trip_id)


@app.post("/trips/{trip_id}/complete")
def complete(trip_id: int, body: CompleteIn):
    with transaction() as conn:
        fare = svc.complete_trip(conn, trip_id, body.distance_km)
        trip = svc.get_trip(conn, trip_id)
    return {"fare_cents": fare, **trip}


@app.post("/trips/{trip_id}/cancel")
def cancel(trip_id: int, body: CancelIn):
    with transaction() as conn:
        svc.cancel_trip(conn, trip_id, body.reason)
        return svc.get_trip(conn, trip_id)


@app.post("/trips/{trip_id}/payment", status_code=201)
def pay(trip_id: int, body: PaymentIn):
    with transaction() as conn:
        pid = svc.record_payment(conn, trip_id, body.method, body.capture)
    return {"id": pid}


@app.post("/trips/{trip_id}/ratings", status_code=201)
def rate(trip_id: int, body: RatingIn):
    with transaction() as conn:
        rid = svc.rate_trip(conn, trip_id, body.rated_by, body.score, body.comment)
    return {"id": rid}


@app.get("/analytics")
def analytics_index():
    return [{"name": p.stem, "title": p.read_text().splitlines()[0].lstrip("- ").strip()} for p in list_queries()]


@app.get("/analytics/{name}")
def analytics_run(name: str, limit: int = Query(default=100, ge=1, le=1000)):
    path = ANALYTICS_DIR / f"{name}.sql"
    if not path.exists() or ".." in name:
        raise HTTPException(404, "unknown query")
    conn = connect()
    try:
        cols, rows, secs = run_query(conn, path)
    finally:
        conn.close()
    return {"query": name, "elapsed_ms": round(secs * 1000), "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows[:limit]]}
