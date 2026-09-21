-- 002_triggers.sql
-- Business rules that need a lookup or maintain a derived value.
-- Every rejection raises SQLSTATE '45000' with a message the API maps to HTTP 409/422.
--
-- Rule of thumb used here:
--   * range and shape rules       -> CHECK constraints (001)
--   * cross row / cross table     -> BEFORE triggers that SIGNAL
--   * derived aggregates + audit  -> AFTER triggers with atomic arithmetic

DELIMITER $$

-- ---------------------------------------------------------------------------
-- drivers: a driver cannot go online until approved.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_drivers_bu
BEFORE UPDATE ON drivers
FOR EACH ROW
BEGIN
    IF NEW.status <> 'offline' AND NEW.approved_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'DRIVER_NOT_APPROVED: driver must be approved before going online';
    END IF;
END$$

-- ---------------------------------------------------------------------------
-- trips: audit the initial state so trip_events is complete for every row,
-- including backfilled / bulk loaded historical trips.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_trips_ai
AFTER INSERT ON trips
FOR EACH ROW
BEGIN
    INSERT INTO trip_events (trip_id, from_status, to_status, occurred_at)
    VALUES (
        NEW.id, NULL, NEW.status,
        CASE NEW.status
            WHEN 'accepted'    THEN NEW.accepted_at
            WHEN 'in_progress' THEN NEW.started_at
            WHEN 'completed'   THEN NEW.completed_at
            WHEN 'cancelled'   THEN NEW.cancelled_at
            ELSE NEW.requested_at
        END
    );
END$$

-- ---------------------------------------------------------------------------
-- trips: the state machine. Terminal rows are immutable. Every transition is
-- validated, timestamps are filled if the caller omitted them, and accepting
-- a trip takes a row lock on the driver so two accepts cannot both succeed.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_trips_bu
BEFORE UPDATE ON trips
FOR EACH ROW
BEGIN
    DECLARE v_driver_status VARCHAR(16);

    IF OLD.status IN ('completed','cancelled') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_TERMINAL: completed or cancelled trips are immutable';
    END IF;

    IF OLD.driver_id IS NOT NULL AND NEW.driver_id <> OLD.driver_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_DRIVER_LOCKED: driver cannot be reassigned once set';
    END IF;

    IF NEW.status <> OLD.status THEN
        IF NOT (
               (OLD.status = 'requested'   AND NEW.status IN ('accepted','cancelled'))
            OR (OLD.status = 'accepted'    AND NEW.status IN ('in_progress','cancelled'))
            OR (OLD.status = 'in_progress' AND NEW.status = 'completed')
        ) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_INVALID_TRANSITION: transition not allowed by state machine';
        END IF;

        IF NEW.status = 'accepted' THEN
            IF NEW.driver_id IS NULL OR NEW.vehicle_id IS NULL THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_NEEDS_DRIVER: accepting requires driver_id and vehicle_id';
            END IF;
            -- Locking read. Under REPEATABLE READ a plain SELECT would read a
            -- stale snapshot and let two concurrent accepts both see 'available'.
            SELECT status INTO v_driver_status
              FROM drivers WHERE user_id = NEW.driver_id FOR UPDATE;
            IF v_driver_status IS NULL OR v_driver_status <> 'available' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'DRIVER_UNAVAILABLE: driver is not available';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM vehicles WHERE id = NEW.vehicle_id AND driver_id = NEW.driver_id AND is_active = 1) THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'VEHICLE_MISMATCH: vehicle is not the active vehicle of this driver';
            END IF;
            SET NEW.accepted_at = COALESCE(NEW.accepted_at, CURRENT_TIMESTAMP(3));
        END IF;

        IF NEW.status = 'in_progress' THEN
            SET NEW.started_at = COALESCE(NEW.started_at, CURRENT_TIMESTAMP(3));
        END IF;

        IF NEW.status = 'completed' THEN
            SET NEW.completed_at = COALESCE(NEW.completed_at, CURRENT_TIMESTAMP(3));
            SET NEW.duration_sec = COALESCE(NEW.duration_sec, TIMESTAMPDIFF(SECOND, NEW.started_at, NEW.completed_at));
            IF NEW.fare_cents IS NULL OR NEW.distance_km IS NULL THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_NEEDS_FARE: completing requires fare_cents and distance_km';
            END IF;
        END IF;

        IF NEW.status = 'cancelled' THEN
            SET NEW.cancelled_at = COALESCE(NEW.cancelled_at, CURRENT_TIMESTAMP(3));
            IF NEW.cancel_reason IS NULL THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_NEEDS_REASON: cancelling requires cancel_reason';
            END IF;
        END IF;

        -- timestamps must be monotone
        IF (NEW.accepted_at  IS NOT NULL AND NEW.accepted_at  < NEW.requested_at)
        OR (NEW.started_at   IS NOT NULL AND NEW.started_at   < NEW.accepted_at)
        OR (NEW.completed_at IS NOT NULL AND NEW.completed_at < NEW.started_at) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TRIP_TIME_ORDER: timestamps must be non decreasing along the lifecycle';
        END IF;
    END IF;
END$$

-- ---------------------------------------------------------------------------
-- trips: after a transition, write the audit row and move the driver.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_trips_au
AFTER UPDATE ON trips
FOR EACH ROW
BEGIN
    IF NEW.status <> OLD.status THEN
        INSERT INTO trip_events (trip_id, from_status, to_status, occurred_at)
        VALUES (NEW.id, OLD.status, NEW.status,
                CASE NEW.status
                    WHEN 'accepted'    THEN NEW.accepted_at
                    WHEN 'in_progress' THEN NEW.started_at
                    WHEN 'completed'   THEN NEW.completed_at
                    WHEN 'cancelled'   THEN NEW.cancelled_at
                END);

        IF NEW.status = 'accepted' THEN
            UPDATE drivers SET status = 'on_trip' WHERE user_id = NEW.driver_id;
        ELSEIF NEW.status = 'completed' THEN
            UPDATE drivers SET status = 'available', current_zone_id = NEW.dropoff_zone_id
             WHERE user_id = NEW.driver_id;
        ELSEIF NEW.status = 'cancelled' AND NEW.driver_id IS NOT NULL THEN
            UPDATE drivers SET status = 'available' WHERE user_id = NEW.driver_id;
        END IF;
    END IF;
END$$

-- ---------------------------------------------------------------------------
-- ratings: only a completed trip can be rated. rated_by says who is giving
-- the score; the counterpart receives it.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_ratings_bi
BEFORE INSERT ON ratings
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(16);
    SELECT status INTO v_status FROM trips WHERE id = NEW.trip_id;
    IF v_status IS NULL OR v_status <> 'completed' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RATING_NOT_COMPLETED: only completed trips can be rated';
    END IF;
END$$

CREATE TRIGGER trg_ratings_ai
AFTER INSERT ON ratings
FOR EACH ROW
BEGIN
    -- Atomic increments. This is the correct fix for the lost update shown in
    -- concurrency/lost_update.py: the arithmetic happens under the row lock,
    -- so two concurrent ratings can never overwrite each other.
    IF NEW.rated_by = 'rider' THEN
        UPDATE drivers d
          JOIN trips t ON t.driver_id = d.user_id
           SET d.rating_sum = d.rating_sum + NEW.score, d.rating_count = d.rating_count + 1
         WHERE t.id = NEW.trip_id;
    ELSE
        UPDATE riders r
          JOIN trips t ON t.rider_id = r.user_id
           SET r.rating_sum = r.rating_sum + NEW.score, r.rating_count = r.rating_count + 1
         WHERE t.id = NEW.trip_id;
    END IF;
END$$

CREATE TRIGGER trg_ratings_bu
BEFORE UPDATE ON ratings
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RATING_IMMUTABLE: ratings cannot be edited, delete and re insert';
END$$

CREATE TRIGGER trg_ratings_ad
AFTER DELETE ON ratings
FOR EACH ROW
BEGIN
    IF OLD.rated_by = 'rider' THEN
        UPDATE drivers d JOIN trips t ON t.driver_id = d.user_id
           SET d.rating_sum = d.rating_sum - OLD.score, d.rating_count = d.rating_count - 1
         WHERE t.id = OLD.trip_id;
    ELSE
        UPDATE riders r JOIN trips t ON t.rider_id = r.user_id
           SET r.rating_sum = r.rating_sum - OLD.score, r.rating_count = r.rating_count - 1
         WHERE t.id = OLD.trip_id;
    END IF;
END$$

-- ---------------------------------------------------------------------------
-- payments: one per completed trip, amount must equal the fare, and the
-- status moves pending -> captured -> refunded only.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_payments_bi
BEFORE INSERT ON payments
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(16);
    DECLARE v_fare INT UNSIGNED;
    SELECT status, fare_cents INTO v_status, v_fare FROM trips WHERE id = NEW.trip_id;
    IF v_status IS NULL OR v_status <> 'completed' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PAYMENT_NOT_COMPLETED: only completed trips can be paid';
    END IF;
    IF NEW.amount_cents <> v_fare THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PAYMENT_AMOUNT_MISMATCH: amount must equal trip fare';
    END IF;
    IF NEW.status = 'captured' THEN
        SET NEW.captured_at = COALESCE(NEW.captured_at, CURRENT_TIMESTAMP(3));
    END IF;
END$$

CREATE TRIGGER trg_payments_bu
BEFORE UPDATE ON payments
FOR EACH ROW
BEGIN
    IF NEW.trip_id <> OLD.trip_id OR NEW.amount_cents <> OLD.amount_cents THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PAYMENT_IMMUTABLE: trip and amount cannot change';
    END IF;
    IF NEW.status <> OLD.status THEN
        IF NOT ((OLD.status = 'pending' AND NEW.status = 'captured')
             OR (OLD.status = 'captured' AND NEW.status = 'refunded')) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PAYMENT_INVALID_TRANSITION: allowed pending->captured->refunded';
        END IF;
        IF NEW.status = 'captured' THEN
            SET NEW.captured_at = COALESCE(NEW.captured_at, CURRENT_TIMESTAMP(3));
        END IF;
    END IF;
END$$

DELIMITER ;
