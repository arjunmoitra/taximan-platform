-- Q07 Cancellation analysis by pickup zone and reason, with the zone's share
-- of all cancellations and its rank. Conditional aggregation + windows.
SELECT z.name                                                       AS pickup_zone,
       COUNT(*)                                                     AS requests,
       SUM(t.status = 'cancelled')                                  AS cancelled,
       ROUND(100 * SUM(t.status = 'cancelled') / COUNT(*), 2)       AS cancel_pct,
       SUM(t.cancel_reason = 'rider')                               AS by_rider,
       SUM(t.cancel_reason = 'driver')                              AS by_driver,
       SUM(t.cancel_reason = 'no_driver')                           AS no_driver,
       SUM(t.cancel_reason = 'system')                              AS by_system,
       ROUND(100 * SUM(t.status = 'cancelled') / SUM(SUM(t.status = 'cancelled')) OVER (), 1) AS share_of_all_cancels,
       RANK() OVER (ORDER BY CAST(SUM(t.status = 'cancelled') AS DOUBLE) / COUNT(*) DESC) AS worst_rank
  FROM trips t
  JOIN zones z ON z.id = t.pickup_zone_id
 WHERE t.requested_at >= UTC_TIMESTAMP() - INTERVAL 90 DAY
 GROUP BY z.name
 ORDER BY worst_rank;
