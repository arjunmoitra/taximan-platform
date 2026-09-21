# Architecture

## Entity relationship diagram

```mermaid
erDiagram
    users ||--o| riders : "is a"
    users ||--o| drivers : "is a"
    drivers ||--o{ vehicles : owns
    zones ||--o{ riders : "home zone"
    zones ||--o{ drivers : "current zone"
    zones ||--o{ trips : pickup
    zones ||--o{ trips : dropoff
    riders ||--o{ trips : requests
    drivers ||--o{ trips : serves
    vehicles ||--o{ trips : "used on"
    trips ||--o{ trip_events : "audit log"
    trips ||--o| payments : "paid by"
    trips ||--o{ ratings : "rated (max 2)"

    users {
        bigint id PK
        varchar email UK
        varchar phone_e164 UK
        varchar full_name
        char password_hash
    }
    riders {
        bigint user_id PK_FK
        smallint home_zone_id FK
        int rating_sum
        int rating_count
    }
    drivers {
        bigint user_id PK_FK
        varchar licence_no UK
        enum status
        smallint current_zone_id FK
        int rating_sum
        int rating_count
        datetime approved_at
    }
    vehicles {
        bigint id PK
        bigint driver_id FK
        varchar plate UK
        tinyint is_active
        bigint active_driver_key "generated, UNIQUE"
    }
    zones {
        smallint id PK
        varchar city
        varchar name
    }
    trips {
        bigint id PK
        bigint rider_id FK
        bigint driver_id FK
        bigint vehicle_id FK
        smallint pickup_zone_id FK
        smallint dropoff_zone_id FK
        enum status
        datetime requested_at
        datetime accepted_at
        datetime started_at
        datetime completed_at
        datetime cancelled_at
        decimal distance_km
        int duration_sec
        decimal surge_multiplier
        int fare_cents
    }
    trip_events {
        bigint id PK
        bigint trip_id FK
        enum from_status
        enum to_status
        datetime occurred_at
    }
    payments {
        bigint id PK
        bigint trip_id FK_UK
        int amount_cents
        enum method
        enum status
    }
    ratings {
        bigint id PK
        bigint trip_id FK
        enum rated_by "UNIQUE with trip_id"
        tinyint score
    }
```

## Normalisation

Every table is in third normal form.

* `users` holds identity once. `riders` and `drivers` are subtypes keyed by
  the same `user_id`, so a person who both rides and drives has one email,
  one phone and one password hash.
* Vehicle attributes live on `vehicles`, not on `drivers`, because a driver
  changes cars. The current car is the one row with `is_active = 1`, and a
  VIRTUAL generated column plus a UNIQUE index guarantee there is at most one.
* Zones are a dimension table. Storing a zone name on every trip would
  repeat it 300k times and make renames a mass update.
* `trip_events` is append only and written solely by triggers. It is the
  answer to "what happened to trip 41 and when", independent of the current
  row.
* `rating_sum` and `rating_count` on `riders` and `drivers` are deliberate
  denormalisation. They are derived from `ratings`, but reading a driver's
  average would otherwise scan their rating history on every dispatch
  decision. The triggers keep them exact and `tests/test_integrity.py`
  recomputes them from scratch to prove it.

## Where each rule lives

| rule | mechanism | why there |
|---|---|---|
| email shape, phone E.164, score 1 to 5, surge 1 to 5, lat/lng ranges | CHECK | single row, no lookup |
| completed trip must have driver, vehicle, fare, distance, duration, completed_at | CHECK | single row |
| one active vehicle per driver | generated column + UNIQUE | declarative, no race |
| one payment per trip, one rating per direction | UNIQUE | declarative |
| trip state machine, terminal immutability, timestamp order | BEFORE UPDATE trigger | compares OLD and NEW |
| accepting needs an available driver | trigger with `SELECT ... FOR UPDATE` | cross table, must lock |
| rating and payment need a completed trip, payment amount equals fare | BEFORE INSERT trigger | cross table lookup |
| rating aggregates, driver status, audit log | AFTER triggers | derived data, atomic arithmetic |
| driver must be approved before going online | BEFORE UPDATE trigger | single table but conditional |

The application layer (`services.py`) adds only what the database cannot
express: fare computation, candidate ranking for dispatch, and the SKIP
LOCKED protocol. It never re checks a rule the database already enforces.

## Indexes

Chosen from the analytical queries and the service paths, not guessed.

| index | serves |
|---|---|
| `trips (rider_id, requested_at)` | rider history, retention cohorts |
| `trips (driver_id, completed_at)` | earnings, driver leaderboard, overlap check |
| `trips (status, requested_at)` | dispatch queue, funnel by day |
| `trips (pickup_zone_id, requested_at)` | zone demand and surge, cancellations by zone |
| `drivers (status, current_zone_id)` | dispatch candidate scan |
| `vehicles (driver_id, is_active)` | active vehicle lookup on accept |
| `payments (status, created_at)` | revenue by day, pending payments |
| `trip_events (trip_id, occurred_at)` | event timeline per trip |

## Money and time

Money is integer cents. `DECIMAL` would be fine, `FLOAT` never is, and
integers make `SUM` exact and fast. Timestamps are `DATETIME(3)` written by
the MySQL clock only. The application never sends its own wall clock time,
because the server and the application host drift by tens of milliseconds
and the trigger enforces that lifecycle timestamps never go backwards.

## Data flow

```
db/migrations/*.sql  --taximan migrate-->  MySQL 8.4 (Docker)
generate.py          --CSV + LOAD DATA-->  same, all triggers firing
services.py          --parameterised SQL, one transaction per operation-->  same
api.py               --FastAPI-->  services.py
db/analytics/*.sql   --taximan analytics / GET /analytics/{name}-->  same
concurrency/*.py     --two raw connections racing-->  same
tests/               --pytest, own database taximan_test-->  same
```
