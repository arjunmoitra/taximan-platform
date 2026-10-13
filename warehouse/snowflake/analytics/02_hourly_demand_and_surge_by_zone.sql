-- Port of db/analytics/02_hourly_demand_and_surge_by_zone.sql
-- Changes: COUNT_IF replaces SUM(<boolean>), which is MySQL only.
CREATE OR REPLACE VIEW analytics.q02_hourly_demand_and_surge_by_zone AS
SELECT z.name                                                  AS pickup_zone,
       HOUR(t.requested_at)                                    AS hour_of_day,
       COUNT(*)                                                AS requests,
       COUNT_IF(t.status = 'completed')                        AS completed,
       ROUND(100 * COUNT_IF(t.status = 'cancelled') / COUNT(*), 1) AS cancel_pct,
       ROUND(AVG(t.surge_multiplier), 2)                       AS avg_surge,
       ROUND(AVG(CASE WHEN t.status = 'completed' THEN t.fare_cents END) / 100, 2) AS avg_fare_dollars
  FROM raw.trips t
  JOIN raw.zones z ON z.id = t.pickup_zone_id
 CROSS JOIN analytics.as_of a
 WHERE t.requested_at >= DATEADD('day', -90, a.as_of)
 GROUP BY z.name, HOUR(t.requested_at)
HAVING COUNT(*) >= 50
 ORDER BY avg_surge DESC, requests DESC;
