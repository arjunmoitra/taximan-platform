-- Port of db/analytics/10_time_to_accept_percentiles.sql
-- Changes: PERCENTILE_DISC replaces the ROW_NUMBER / CEIL workaround MySQL
-- needs. It is the nearest rank method, so it returns exactly the value the
-- original picked at row CEIL(p * n). Seconds use the same truncating
-- millisecond form as Q04.
CREATE OR REPLACE VIEW analytics.q10_time_to_accept_percentiles AS
WITH waits AS (
    SELECT t.pickup_zone_id,
           TRUNC(DATEDIFF('millisecond', t.requested_at, t.accepted_at) / 1000) AS wait_sec
      FROM raw.trips t
     CROSS JOIN analytics.as_of a
     WHERE t.accepted_at IS NOT NULL
       AND t.requested_at >= DATEADD('day', -30, a.as_of)
)
SELECT z.name AS pickup_zone,
       COUNT(*)                                                AS accepted_trips,
       PERCENTILE_DISC(0.50) WITHIN GROUP (ORDER BY w.wait_sec) AS p50_sec,
       PERCENTILE_DISC(0.90) WITHIN GROUP (ORDER BY w.wait_sec) AS p90_sec,
       PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY w.wait_sec) AS p99_sec
  FROM waits w
  JOIN raw.zones z ON z.id = w.pickup_zone_id
 GROUP BY z.name
 ORDER BY p90_sec DESC;
