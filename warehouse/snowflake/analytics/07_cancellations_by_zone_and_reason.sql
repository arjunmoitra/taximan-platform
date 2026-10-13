-- Port of db/analytics/07_cancellations_by_zone_and_reason.sql
-- Changes: COUNT_IF replaces SUM(<boolean>). The rank orders by a DOUBLE ratio so it does not
-- depend on an engine's decimal division scale (see the MySQL original).
CREATE OR REPLACE VIEW analytics.q07_cancellations_by_zone_and_reason AS
SELECT z.name                                                       AS pickup_zone,
       COUNT(*)                                                     AS requests,
       COUNT_IF(t.status = 'cancelled')                             AS cancelled,
       ROUND(100 * COUNT_IF(t.status = 'cancelled') / COUNT(*), 2)  AS cancel_pct,
       COUNT_IF(t.cancel_reason = 'rider')                          AS by_rider,
       COUNT_IF(t.cancel_reason = 'driver')                         AS by_driver,
       COUNT_IF(t.cancel_reason = 'no_driver')                      AS no_driver,
       COUNT_IF(t.cancel_reason = 'system')                         AS by_system,
       ROUND(100 * COUNT_IF(t.status = 'cancelled') / SUM(COUNT_IF(t.status = 'cancelled')) OVER (), 1) AS share_of_all_cancels,
       RANK() OVER (ORDER BY CAST(COUNT_IF(t.status = 'cancelled') AS DOUBLE) / COUNT(*) DESC) AS worst_rank
  FROM raw.trips t
  JOIN raw.zones z ON z.id = t.pickup_zone_id
 CROSS JOIN analytics.as_of a
 WHERE t.requested_at >= DATEADD('day', -90, a.as_of)
 GROUP BY z.name
 ORDER BY worst_rank;
