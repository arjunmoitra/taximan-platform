-- Port of db/analytics/01_driver_earnings_leaderboard.sql
-- Changes: drivers are identified by driver_id (no names in the warehouse), the
-- window is anchored on analytics.as_of, and the LIMIT is left to the consumer.
-- dollars_per_hour is gross_cents * 36 / seconds, a single division (see the MySQL original).
CREATE OR REPLACE VIEW analytics.q01_driver_earnings_leaderboard AS
WITH earnings AS (
    SELECT t.driver_id,
           COUNT(*)                     AS trips,
           SUM(t.fare_cents)            AS gross_cents,
           SUM(t.distance_km)           AS km,
           SUM(t.duration_sec)          AS seconds_on_trip
      FROM raw.trips t
     CROSS JOIN analytics.as_of a
     WHERE t.status = 'completed'
       AND t.completed_at >= DATEADD('day', -30, a.as_of)
     GROUP BY t.driver_id
)
SELECT RANK() OVER (ORDER BY e.gross_cents DESC)                  AS rnk,
       e.driver_id,
       v.make, v.model,
       e.trips,
       ROUND(e.gross_cents / 100, 2)                              AS gross_dollars,
       ROUND(e.gross_cents * 36 / NULLIF(e.seconds_on_trip, 0), 2) AS dollars_per_hour,
       ROUND(e.km, 1)                                             AS km,
       ROUND(d.rating_sum / NULLIF(d.rating_count, 0), 2)         AS rating,
       ROUND(e.gross_cents / AVG(e.gross_cents) OVER (), 2)       AS x_avg_driver
  FROM earnings e
  JOIN raw.drivers d       ON d.user_id = e.driver_id
  LEFT JOIN raw.vehicles v ON v.driver_id = d.user_id AND v.is_active = TRUE
 ORDER BY rnk;
