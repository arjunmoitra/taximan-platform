-- Port of db/analytics/08_fare_per_km_by_vehicle_make.sql
-- Unchanged apart from schema qualification. Snowflake has MEDIAN and
-- PERCENTILE_CONT, but those interpolate and would not reproduce the original
-- bucket based numbers, so the NTILE form is kept for parity.
CREATE OR REPLACE VIEW analytics.q08_fare_per_km_by_vehicle_make AS
WITH per_trip AS (
    SELECT v.make,
           t.fare_cents / t.distance_km AS cents_per_km,
           NTILE(100) OVER (PARTITION BY v.make ORDER BY t.fare_cents / t.distance_km) AS pct
      FROM raw.trips t
      JOIN raw.vehicles v ON v.id = t.vehicle_id
     WHERE t.status = 'completed' AND t.distance_km >= 1
)
SELECT make,
       COUNT(*)                                                      AS trips,
       ROUND(AVG(cents_per_km) / 100, 3)                             AS mean_dollars_per_km,
       ROUND(MIN(CASE WHEN pct = 50 THEN cents_per_km END) / 100, 3) AS median_dollars_per_km,
       ROUND(MIN(CASE WHEN pct = 90 THEN cents_per_km END) / 100, 3) AS p90_dollars_per_km
  FROM per_trip
 GROUP BY make
 ORDER BY trips DESC;
