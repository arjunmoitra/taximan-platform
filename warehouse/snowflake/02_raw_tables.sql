-- Typed landing tables. Column names and order match the extract allowlist in
-- src/taximan/warehouse/spec.py, and a test fails if the two drift apart.
--
-- Deliberately absent: users (email, phone, password hash, full name),
-- drivers.licence_no, vehicles.plate and ratings.comment. Personal data is
-- excluded by construction, not masked after the fact.
-- Constraints are informational in Snowflake (not enforced). The rules live in
-- MySQL, which is the system of record.

CREATE OR REPLACE TABLE raw.zones (
    id            INTEGER       NOT NULL,
    city          VARCHAR       NOT NULL,
    name          VARCHAR       NOT NULL,
    centroid_lat  NUMBER(9, 6)  NOT NULL,
    centroid_lng  NUMBER(9, 6)  NOT NULL,
    PRIMARY KEY (id)
);

CREATE OR REPLACE TABLE raw.riders (
    user_id       BIGINT        NOT NULL,
    home_zone_id  INTEGER,
    rating_sum    BIGINT        NOT NULL,
    rating_count  BIGINT        NOT NULL,
    created_at    TIMESTAMP_NTZ(3) NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE OR REPLACE TABLE raw.drivers (
    user_id          BIGINT        NOT NULL,
    status           VARCHAR       NOT NULL,
    current_zone_id  INTEGER,
    rating_sum       BIGINT        NOT NULL,
    rating_count     BIGINT        NOT NULL,
    approved_at      TIMESTAMP_NTZ(3),
    created_at       TIMESTAMP_NTZ(3) NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE OR REPLACE TABLE raw.vehicles (
    id          BIGINT        NOT NULL,
    driver_id   BIGINT        NOT NULL,
    make        VARCHAR       NOT NULL,
    model       VARCHAR       NOT NULL,
    model_year  INTEGER       NOT NULL,
    seats       INTEGER       NOT NULL,
    is_active   BOOLEAN       NOT NULL,
    created_at  TIMESTAMP_NTZ(3) NOT NULL,
    PRIMARY KEY (id)
);

CREATE OR REPLACE TABLE raw.trips (
    id                BIGINT        NOT NULL,
    rider_id          BIGINT        NOT NULL,
    driver_id         BIGINT,
    vehicle_id        BIGINT,
    pickup_zone_id    INTEGER       NOT NULL,
    dropoff_zone_id   INTEGER       NOT NULL,
    status            VARCHAR       NOT NULL,
    requested_at      TIMESTAMP_NTZ(3) NOT NULL,
    accepted_at       TIMESTAMP_NTZ(3),
    started_at        TIMESTAMP_NTZ(3),
    completed_at      TIMESTAMP_NTZ(3),
    cancelled_at      TIMESTAMP_NTZ(3),
    cancel_reason     VARCHAR,
    distance_km       NUMBER(6, 2),
    duration_sec      BIGINT,
    surge_multiplier  NUMBER(3, 2)  NOT NULL,
    fare_cents        BIGINT,
    PRIMARY KEY (id)
);

CREATE OR REPLACE TABLE raw.trip_events (
    id           BIGINT        NOT NULL,
    trip_id      BIGINT        NOT NULL,
    from_status  VARCHAR,
    to_status    VARCHAR       NOT NULL,
    occurred_at  TIMESTAMP_NTZ(3) NOT NULL,
    PRIMARY KEY (id)
);

CREATE OR REPLACE TABLE raw.payments (
    id            BIGINT        NOT NULL,
    trip_id       BIGINT        NOT NULL,
    amount_cents  BIGINT        NOT NULL,
    method        VARCHAR       NOT NULL,
    status        VARCHAR       NOT NULL,
    captured_at   TIMESTAMP_NTZ(3),
    created_at    TIMESTAMP_NTZ(3) NOT NULL,
    PRIMARY KEY (id)
);

CREATE OR REPLACE TABLE raw.ratings (
    id          BIGINT        NOT NULL,
    trip_id     BIGINT        NOT NULL,
    rated_by    VARCHAR       NOT NULL,
    score       INTEGER       NOT NULL,
    created_at  TIMESTAMP_NTZ(3) NOT NULL,
    PRIMARY KEY (id)
);
