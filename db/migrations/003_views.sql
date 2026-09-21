-- 003_views.sql
-- Read models. Views keep the aggregate arithmetic in one place so no report
-- divides rating_sum by rating_count differently.

CREATE OR REPLACE VIEW v_driver_profile AS
SELECT d.user_id,
       u.full_name,
       d.status,
       d.current_zone_id,
       d.rating_count,
       CASE WHEN d.rating_count = 0 THEN NULL
            ELSE ROUND(d.rating_sum / d.rating_count, 2) END AS rating_avg,
       v.id   AS active_vehicle_id,
       v.make, v.model, v.plate
  FROM drivers d
  JOIN users u          ON u.id = d.user_id
  LEFT JOIN vehicles v  ON v.driver_id = d.user_id AND v.is_active = 1;

CREATE OR REPLACE VIEW v_rider_profile AS
SELECT r.user_id,
       u.full_name,
       r.home_zone_id,
       r.rating_count,
       CASE WHEN r.rating_count = 0 THEN NULL
            ELSE ROUND(r.rating_sum / r.rating_count, 2) END AS rating_avg
  FROM riders r
  JOIN users u ON u.id = r.user_id;

CREATE OR REPLACE VIEW v_trip_detail AS
SELECT t.id, t.status, t.requested_at, t.accepted_at, t.started_at, t.completed_at, t.cancelled_at,
       t.cancel_reason, t.distance_km, t.duration_sec, t.surge_multiplier, t.fare_cents,
       t.rider_id,  ru.full_name AS rider_name,
       t.driver_id, du.full_name AS driver_name,
       pz.name AS pickup_zone, dz.name AS dropoff_zone,
       p.status AS payment_status, p.method AS payment_method
  FROM trips t
  JOIN users ru        ON ru.id = t.rider_id
  LEFT JOIN users du   ON du.id = t.driver_id
  JOIN zones pz        ON pz.id = t.pickup_zone_id
  JOIN zones dz        ON dz.id = t.dropoff_zone_id
  LEFT JOIN payments p ON p.trip_id = t.id;
