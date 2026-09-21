-- Q04 Daily trip funnel: requested -> accepted -> completed, with time to
-- accept and the day over day change in completion rate (LAG).
WITH daily AS (
    SELECT DATE(t.requested_at)                                      AS day,
           COUNT(*)                                                  AS requested,
           SUM(t.accepted_at IS NOT NULL)                            AS accepted,
           SUM(t.status = 'completed')                               AS completed,
           SUM(t.status = 'cancelled' AND t.cancel_reason = 'no_driver') AS unserved,
           AVG(TIMESTAMPDIFF(SECOND, t.requested_at, t.accepted_at)) AS avg_sec_to_accept
      FROM trips t
     WHERE t.requested_at >= UTC_TIMESTAMP() - INTERVAL 14 DAY
       AND t.requested_at <  UTC_TIMESTAMP() - INTERVAL 1 DAY  -- exclude today, still in flight
     GROUP BY DATE(t.requested_at)
)
SELECT day,
       requested,
       accepted,
       completed,
       unserved,
       ROUND(100 * completed / requested, 1)                                        AS completion_pct,
       ROUND(100 * completed / requested - LAG(100 * completed / requested) OVER (ORDER BY day), 1) AS completion_pct_dod,
       ROUND(avg_sec_to_accept)                                                     AS avg_sec_to_accept
  FROM daily
 ORDER BY day;
