"""HTTP lifecycle through FastAPI's TestClient against the real database."""
import os

import pytest
from fastapi.testclient import TestClient

from taximan.api import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _user(client, tag):
    n = abs(hash((tag, os.getpid()))) % 10_000_000
    r = client.post("/users", json={"email": f"api.{tag}.{n}@example.com", "phone_e164": f"+1555{n:07d}",
                                    "full_name": f"Api {tag}", "password": "password123"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_full_lifecycle(client):
    rider = _user(client, "rider")
    assert client.post("/riders", json={"user_id": rider, "home_zone_id": 1}).status_code == 201
    driver = _user(client, "driver")
    assert client.post("/drivers", json={"user_id": driver, "licence_no": f"API-{driver}", "zone_id": 1}).status_code == 201
    r = client.put(f"/drivers/{driver}/status", json={"status": "available"})
    assert r.status_code == 409 and r.json()["error"] == "DRIVER_NOT_APPROVED"
    assert client.post(f"/drivers/{driver}/approve").status_code == 200
    assert client.put(f"/drivers/{driver}/status", json={"status": "available"}).json()["status"] == "available"
    assert client.post(f"/drivers/{driver}/vehicles", json={"plate": f"AP{driver}", "make": "Kia", "model": "Soul", "model_year": 2022}).status_code == 201

    trip = client.post("/trips", json={"rider_id": rider, "pickup_zone_id": 1, "dropoff_zone_id": 2}).json()
    tid = trip["id"]
    assert trip["status"] == "requested"
    r = client.post(f"/trips/{tid}/ratings", json={"rated_by": "rider", "score": 5})
    assert r.status_code == 409 and r.json()["error"] == "RATING_NOT_COMPLETED"
    assert client.post(f"/trips/{tid}/accept", json={"driver_id": driver}).json()["status"] == "accepted"
    assert client.post(f"/trips/{tid}/accept", json={"driver_id": driver}).status_code == 409
    assert client.post(f"/trips/{tid}/start").json()["status"] == "in_progress"
    done = client.post(f"/trips/{tid}/complete", json={"distance_km": 6.3}).json()
    assert done["status"] == "completed" and done["fare_cents"] >= 600
    assert client.post(f"/trips/{tid}/payment", json={"method": "card"}).status_code == 201
    assert client.post(f"/trips/{tid}/ratings", json={"rated_by": "rider", "score": 5}).status_code == 201
    assert client.post(f"/trips/{tid}/ratings", json={"rated_by": "driver", "score": 7}).status_code == 422
    events = client.get(f"/trips/{tid}/events").json()
    assert [e["to_status"] for e in events] == ["requested", "accepted", "in_progress", "completed"]
    earn = client.get(f"/drivers/{driver}/earnings").json()
    assert earn["trips"] == 1 and earn["gross_cents"] == done["fare_cents"]
    assert client.get(f"/drivers/{driver}").json()["rating_avg"] == 5


def test_not_found_and_analytics(client):
    assert client.get("/trips/999999999").status_code == 404
    assert client.get("/analytics/does_not_exist").status_code == 404
    idx = client.get("/analytics").json()
    assert len(idx) == 12
    body = client.get(f"/analytics/{idx[0]['name']}?limit=3").json()
    assert body["columns"] and len(body["rows"]) <= 3
