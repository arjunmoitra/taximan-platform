-- Port of db/analytics/04_trip_funnel_daily.sql
-- Changes: seconds to accept are computed as TRUNC(DATEDIFF('millisecond') / 1000).
-- A plain DATEDIFF('second') counts second boundaries crossed, so 0.8s to 5.5s
-- (4.7s elapsed) gives 5 where MySQL's TIMESTAMPDIFF(SECOND) gives 4.
CREATE OR REPLACE VIEW analytics.q04_trip_funnel_daily AS
WITH daily AS (
    SELECT CAST(t.requested_at AS DATE)                                  AS day,
           COUNT(*)                                                      AS requested,
           COUNT_IF(t.accepted_at IS NOT NULL)                           AS accepted,
           COUNT_IF(t.status = 'completed')                              AS completed,
           COUNT_IF(t.status = 'cancelled' AND t.cancel_reason = 'no_driver') AS unserved,
           AVG(TRUNC(DATEDIFF('millisecond', t.requested_at, t.accepted_at) / 1000)) AS avg_sec_to_accept
      FROM raw.trips t
     CROSS JOIN analytics.as_of a
     WHERE t.requested_at >= DATEADD('day', -14, a.as_of)
       AND t.requested_at <  DATEADD('day', -1, a.as_of)  -- exclude the latest day, still in flight
     GROUP BY CAST(t.requested_at AS DATE)
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
