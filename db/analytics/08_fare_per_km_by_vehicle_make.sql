-- Q08 Fare per km distribution by vehicle make: median via NTILE, plus mean.
-- Joins trips -> vehicles, uses NTILE(100) to get a percentile without a
-- median function.
WITH per_trip AS (
    SELECT v.make,
           t.fare_cents / t.distance_km AS cents_per_km,
           NTILE(100) OVER (PARTITION BY v.make ORDER BY t.fare_cents / t.distance_km) AS pct
      FROM trips t
      JOIN vehicles v ON v.id = t.vehicle_id
     WHERE t.status = 'completed' AND t.distance_km >= 1
)
SELECT make,
       COUNT(*)                                                    AS trips,
       ROUND(AVG(cents_per_km) / 100, 3)                           AS mean_dollars_per_km,
       ROUND(MIN(CASE WHEN pct = 50 THEN cents_per_km END) / 100, 3) AS median_dollars_per_km,
       ROUND(MIN(CASE WHEN pct = 90 THEN cents_per_km END) / 100, 3) AS p90_dollars_per_km
  FROM per_trip
 GROUP BY make
 ORDER BY trips DESC;
