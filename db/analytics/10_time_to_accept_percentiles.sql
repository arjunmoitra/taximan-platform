-- Q10 Time to accept p50 / p90 / p99 per pickup zone.
-- Percentiles computed with ROW_NUMBER and COUNT over partitions; MySQL has
-- no PERCENTILE_CONT so this is the idiomatic way.
WITH waits AS (
    SELECT t.pickup_zone_id,
           TIMESTAMPDIFF(SECOND, t.requested_at, t.accepted_at) AS wait_sec,
           ROW_NUMBER() OVER (PARTITION BY t.pickup_zone_id ORDER BY TIMESTAMPDIFF(SECOND, t.requested_at, t.accepted_at)) AS rn,
           COUNT(*)     OVER (PARTITION BY t.pickup_zone_id) AS n
      FROM trips t
     WHERE t.accepted_at IS NOT NULL
       AND t.requested_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
)
SELECT z.name AS pickup_zone,
       MAX(w.n)                                                   AS accepted_trips,
       MAX(CASE WHEN w.rn = CEIL(0.50 * w.n) THEN w.wait_sec END) AS p50_sec,
       MAX(CASE WHEN w.rn = CEIL(0.90 * w.n) THEN w.wait_sec END) AS p90_sec,
       MAX(CASE WHEN w.rn = CEIL(0.99 * w.n) THEN w.wait_sec END) AS p99_sec
  FROM waits w
  JOIN zones z ON z.id = w.pickup_zone_id
 GROUP BY z.name
 ORDER BY p90_sec DESC;
