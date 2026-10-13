-- Q11 Drivers whose recent ratings are falling.
-- Compares the average of the last 20 ratings with the 20 before, using
-- ROW_NUMBER over the driver's rating history. Flags a drop of 0.5 or more.
WITH hist AS (
    SELECT t.driver_id,
           r.score,
           ROW_NUMBER() OVER (PARTITION BY t.driver_id ORDER BY r.created_at DESC, r.id DESC) AS recency
      FROM ratings r
      JOIN trips t ON t.id = r.trip_id
     WHERE r.rated_by = 'rider'
),
windows AS (
    SELECT driver_id,
           AVG(CASE WHEN recency <= 20 THEN score END)                 AS last_20,
           AVG(CASE WHEN recency BETWEEN 21 AND 40 THEN score END)     AS prior_20,
           COUNT(*)                                                    AS total_ratings
      FROM hist
     WHERE recency <= 40
     GROUP BY driver_id
    HAVING COUNT(*) = 40
)
SELECT u.full_name,
       w.total_ratings,
       ROUND(w.prior_20, 2)            AS prior_20_avg,
       ROUND(w.last_20, 2)             AS last_20_avg,
       ROUND(w.last_20 - w.prior_20, 2) AS delta
  FROM windows w
  JOIN users u ON u.id = w.driver_id
 WHERE w.last_20 - w.prior_20 <= -0.5
 ORDER BY delta
 LIMIT 20;
