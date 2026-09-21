-- Q02 Demand, fare and surge by pickup zone and hour of day.
-- Shows where and when the market is tight. Uses a zone dimension join and
-- conditional aggregation for cancellation share.
SELECT z.name                                             AS pickup_zone,
       HOUR(t.requested_at)                               AS hour_of_day,
       COUNT(*)                                           AS requests,
       SUM(t.status = 'completed')                        AS completed,
       ROUND(100 * SUM(t.status = 'cancelled') / COUNT(*), 1) AS cancel_pct,
       ROUND(AVG(t.surge_multiplier), 2)                  AS avg_surge,
       ROUND(AVG(CASE WHEN t.status = 'completed' THEN t.fare_cents END) / 100, 2) AS avg_fare_dollars
  FROM trips t
  JOIN zones z ON z.id = t.pickup_zone_id
 WHERE t.requested_at >= UTC_TIMESTAMP() - INTERVAL 90 DAY
 GROUP BY z.name, HOUR(t.requested_at)
HAVING COUNT(*) >= 50
 ORDER BY avg_surge DESC, requests DESC
 LIMIT 25;
