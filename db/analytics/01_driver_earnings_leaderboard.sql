-- Q01 Driver earnings leaderboard, last 30 days.
-- Joins trips -> drivers -> users -> vehicles, aggregates, ranks with a window.
-- Business question: who are the top earning drivers and how do they compare to the median?
WITH earnings AS (
    SELECT t.driver_id,
           COUNT(*)                         AS trips,
           SUM(t.fare_cents)                AS gross_cents,
           SUM(t.distance_km)               AS km,
           SUM(t.duration_sec)              AS seconds_on_trip
      FROM trips t
     WHERE t.status = 'completed'
       AND t.completed_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
     GROUP BY t.driver_id
)
SELECT RANK() OVER (ORDER BY e.gross_cents DESC)                 AS rnk,
       u.full_name,
       v.make, v.model,
       e.trips,
       ROUND(e.gross_cents / 100, 2)                              AS gross_dollars,
       -- gross dollars per hour on trip is gross_cents * 36 / seconds. One division only:
       -- dividing seconds by 3600.0 first rounds to 4 decimals in MySQL and skews short trips.
       ROUND(e.gross_cents * 36 / NULLIF(e.seconds_on_trip, 0), 2) AS dollars_per_hour,
       ROUND(e.km, 1)                                             AS km,
       ROUND(d.rating_sum / NULLIF(d.rating_count, 0), 2)         AS rating,
       ROUND(e.gross_cents / AVG(e.gross_cents) OVER (), 2)       AS x_avg_driver
  FROM earnings e
  JOIN drivers d        ON d.user_id = e.driver_id
  JOIN users u          ON u.id = d.user_id
  LEFT JOIN vehicles v  ON v.driver_id = d.user_id AND v.is_active = 1
 ORDER BY rnk
 LIMIT 20;
