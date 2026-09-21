-- 001_schema.sql
-- Core relational schema for the Taximan ride hailing platform.
-- Third normal form. Every fact lives in exactly one place. Derived values
-- (rating aggregates, driver status) are maintained by triggers in 002.
--
-- Conventions
--   * BIGINT UNSIGNED surrogate keys, AUTO_INCREMENT.
--   * Money is stored as integer cents. Never DECIMAL, never FLOAT.
--   * Timestamps are DATETIME(3) in UTC. The application never writes local time.
--   * Every foreign key states its ON DELETE behaviour explicitly.
--   * CHECK constraints hold the invariants that do not need a lookup.
--     Invariants that need a lookup (rating requires a completed trip) are triggers.

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- users: one row per person who can authenticate. Riders and drivers are
-- subtypes that share this identity. A person can be both.
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email         VARCHAR(254)    NOT NULL,
    phone_e164    VARCHAR(16)     NOT NULL,
    full_name     VARCHAR(120)    NOT NULL,
    password_hash CHAR(60)        NOT NULL COMMENT 'bcrypt, never plaintext',
    created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_phone (phone_e164),
    CONSTRAINT chk_users_email CHECK (email LIKE '%_@_%.__%'),
    CONSTRAINT chk_users_phone CHECK (phone_e164 REGEXP '^\\+[1-9][0-9]{6,14}$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------------
-- riders: subtype of users. rating_* are aggregates maintained by trigger
-- trg_ratings_ai so a read never has to scan the ratings table.
-- ---------------------------------------------------------------------------
CREATE TABLE riders (
    user_id       BIGINT UNSIGNED NOT NULL,
    home_zone_id  SMALLINT UNSIGNED NULL,
    rating_sum    INT UNSIGNED    NOT NULL DEFAULT 0,
    rating_count  INT UNSIGNED    NOT NULL DEFAULT 0,
    created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (user_id),
    CONSTRAINT fk_riders_user FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- zones: coarse geography used for dispatch and analytics. A trip has a
-- pickup zone and a dropoff zone. Keeping zones as a table rather than free
-- text is what makes "cancellations by zone" a join instead of a LIKE.
-- ---------------------------------------------------------------------------
CREATE TABLE zones (
    id         SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    city       VARCHAR(60)  NOT NULL,
    name       VARCHAR(80)  NOT NULL,
    centroid_lat DECIMAL(9,6) NOT NULL,
    centroid_lng DECIMAL(9,6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_zones_city_name (city, name),
    CONSTRAINT chk_zones_lat CHECK (centroid_lat BETWEEN -90 AND 90),
    CONSTRAINT chk_zones_lng CHECK (centroid_lng BETWEEN -180 AND 180)
) ENGINE=InnoDB;

ALTER TABLE riders
    ADD CONSTRAINT fk_riders_home_zone FOREIGN KEY (home_zone_id) REFERENCES zones (id)
        ON DELETE SET NULL ON UPDATE RESTRICT;

-- ---------------------------------------------------------------------------
-- drivers: subtype of users. status is the dispatch state and is the row
-- that concurrent bookings contend for. See concurrency/SCHEDULES.md.
-- ---------------------------------------------------------------------------
CREATE TABLE drivers (
    user_id        BIGINT UNSIGNED NOT NULL,
    licence_no     VARCHAR(32)     NOT NULL,
    status         ENUM('offline','available','on_trip') NOT NULL DEFAULT 'offline',
    current_zone_id SMALLINT UNSIGNED NULL,
    rating_sum     INT UNSIGNED    NOT NULL DEFAULT 0,
    rating_count   INT UNSIGNED    NOT NULL DEFAULT 0,
    approved_at    DATETIME(3)     NULL,
    created_at     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_drivers_licence (licence_no),
    KEY ix_drivers_status_zone (status, current_zone_id),
    CONSTRAINT fk_drivers_user FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_drivers_zone FOREIGN KEY (current_zone_id) REFERENCES zones (id)
        ON DELETE SET NULL ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- vehicles: a driver may register several vehicles over time, at most one is
-- active at a time (enforced by the generated column + UNIQUE index below).
-- ---------------------------------------------------------------------------
CREATE TABLE vehicles (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    driver_id   BIGINT UNSIGNED NOT NULL,
    plate       VARCHAR(16)     NOT NULL,
    make        VARCHAR(40)     NOT NULL,
    model       VARCHAR(40)     NOT NULL,
    model_year  SMALLINT UNSIGNED NOT NULL,
    seats       TINYINT UNSIGNED NOT NULL DEFAULT 4,
    is_active   TINYINT(1)      NOT NULL DEFAULT 1,
    -- generated key that is NULL for inactive vehicles: UNIQUE ignores NULLs, so
    -- this enforces "at most one active vehicle per driver" with no trigger.
    active_driver_key BIGINT UNSIGNED AS (IF(is_active = 1, driver_id, NULL)) VIRTUAL,
    created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uq_vehicles_plate (plate),
    UNIQUE KEY uq_vehicles_one_active_per_driver (active_driver_key),
    KEY ix_vehicles_driver_active (driver_id, is_active),
    CONSTRAINT fk_vehicles_driver FOREIGN KEY (driver_id) REFERENCES drivers (user_id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT chk_vehicles_year  CHECK (model_year BETWEEN 1990 AND 2100),
    CONSTRAINT chk_vehicles_seats CHECK (seats BETWEEN 1 AND 8)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- trips: the central fact table. One row per ride request, from the moment
-- it is requested through completion or cancellation.
--
-- State machine (enforced by trg_trips_bu in 002):
--   requested -> accepted   | cancelled
--   accepted  -> in_progress | cancelled
--   in_progress -> completed
--   completed, cancelled are terminal
-- ---------------------------------------------------------------------------
CREATE TABLE trips (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    rider_id         BIGINT UNSIGNED NOT NULL,
    driver_id        BIGINT UNSIGNED NULL,
    vehicle_id       BIGINT UNSIGNED NULL,
    pickup_zone_id   SMALLINT UNSIGNED NOT NULL,
    dropoff_zone_id  SMALLINT UNSIGNED NOT NULL,
    status           ENUM('requested','accepted','in_progress','completed','cancelled') NOT NULL DEFAULT 'requested',
    requested_at     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    accepted_at      DATETIME(3)     NULL,
    started_at       DATETIME(3)     NULL,
    completed_at     DATETIME(3)     NULL,
    cancelled_at     DATETIME(3)     NULL,
    cancel_reason    ENUM('rider','driver','no_driver','system') NULL,
    distance_km      DECIMAL(6,2)    NULL,
    duration_sec     INT UNSIGNED    NULL,
    surge_multiplier DECIMAL(3,2)    NOT NULL DEFAULT 1.00,
    fare_cents       INT UNSIGNED    NULL,
    PRIMARY KEY (id),
    KEY ix_trips_rider_requested   (rider_id, requested_at),
    KEY ix_trips_driver_completed  (driver_id, completed_at),
    KEY ix_trips_status_requested  (status, requested_at),
    KEY ix_trips_pickup_requested  (pickup_zone_id, requested_at),
    KEY ix_trips_requested_at      (requested_at),
    CONSTRAINT fk_trips_rider   FOREIGN KEY (rider_id)  REFERENCES riders (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_trips_driver  FOREIGN KEY (driver_id) REFERENCES drivers (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_trips_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_trips_pickup  FOREIGN KEY (pickup_zone_id)  REFERENCES zones (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_trips_dropoff FOREIGN KEY (dropoff_zone_id) REFERENCES zones (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_trips_surge     CHECK (surge_multiplier BETWEEN 1.00 AND 5.00),
    CONSTRAINT chk_trips_distance  CHECK (distance_km IS NULL OR distance_km >= 0),
    -- a completed trip must carry its economics; a terminal trip must carry its timestamp
    CONSTRAINT chk_trips_completed CHECK (
        status <> 'completed'
        OR (driver_id IS NOT NULL AND vehicle_id IS NOT NULL AND completed_at IS NOT NULL
            AND fare_cents IS NOT NULL AND distance_km IS NOT NULL AND duration_sec IS NOT NULL)
    ),
    CONSTRAINT chk_trips_cancelled CHECK (
        status <> 'cancelled' OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL)
    ),
    CONSTRAINT chk_trips_accepted CHECK (
        status NOT IN ('accepted','in_progress') OR (driver_id IS NOT NULL AND accepted_at IS NOT NULL)
    )
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- trip_events: append only audit log of every status transition. Written by
-- trigger, never by the application, so it cannot be skipped or forged.
-- ---------------------------------------------------------------------------
CREATE TABLE trip_events (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trip_id     BIGINT UNSIGNED NOT NULL,
    from_status ENUM('requested','accepted','in_progress','completed','cancelled') NULL,
    to_status   ENUM('requested','accepted','in_progress','completed','cancelled') NOT NULL,
    occurred_at DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    KEY ix_trip_events_trip (trip_id, occurred_at),
    CONSTRAINT fk_trip_events_trip FOREIGN KEY (trip_id) REFERENCES trips (id)
        ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- payments: exactly one payment per completed trip (UNIQUE trip_id).
-- amount must equal the trip fare; checked by trigger because it needs a lookup.
-- ---------------------------------------------------------------------------
CREATE TABLE payments (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trip_id      BIGINT UNSIGNED NOT NULL,
    amount_cents INT UNSIGNED    NOT NULL,
    method       ENUM('card','cash','wallet') NOT NULL,
    status       ENUM('pending','captured','refunded') NOT NULL DEFAULT 'pending',
    captured_at  DATETIME(3)     NULL,
    created_at   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uq_payments_trip (trip_id),
    KEY ix_payments_status_created (status, created_at),
    CONSTRAINT fk_payments_trip FOREIGN KEY (trip_id) REFERENCES trips (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_payments_captured CHECK (status <> 'captured' OR captured_at IS NOT NULL)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- ratings: at most one rating per (trip, direction). A rider rates the driver
-- and a driver rates the rider. Score range is a CHECK. Eligibility (trip is
-- completed, rater is a party to the trip) is a trigger.
-- ---------------------------------------------------------------------------
CREATE TABLE ratings (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trip_id    BIGINT UNSIGNED NOT NULL,
    rated_by   ENUM('rider','driver') NOT NULL COMMENT 'who is giving the rating',
    score      TINYINT UNSIGNED NOT NULL,
    comment    VARCHAR(500)    NULL,
    created_at DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uq_ratings_trip_direction (trip_id, rated_by),
    CONSTRAINT fk_ratings_trip FOREIGN KEY (trip_id) REFERENCES trips (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT chk_ratings_score CHECK (score BETWEEN 1 AND 5)
) ENGINE=InnoDB;
