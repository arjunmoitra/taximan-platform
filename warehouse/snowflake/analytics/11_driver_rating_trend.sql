-- Port of db/analytics/11_driver_rating_trend.sql
-- Changes: drivers are identified by driver_id. r.id is the tie-breaker in the
-- recency ordering so two ratings with the same timestamp always fall in the
-- same window.
CREATE OR REPLACE VIEW analytics.q11_driver_rating_trend AS
WITH hist AS (
    SELECT t.driver_id,
           r.score,
           ROW_NUMBER() OVER (PARTITION BY t.driver_id ORDER BY r.created_at DESC, r.id DESC) AS recency
      FROM raw.ratings r
      JOIN raw.trips t ON t.id = r.trip_id
     WHERE r.rated_by = 'rider'
),
windows AS (
    SELECT driver_id,
           AVG(CASE WHEN recency <= 20 THEN score END)             AS last_20,
           AVG(CASE WHEN recency BETWEEN 21 AND 40 THEN score END) AS prior_20,
           COUNT(*)                                                AS total_ratings
      FROM hist
     WHERE recency <= 40
     GROUP BY driver_id
    HAVING COUNT(*) = 40
)
SELECT w.driver_id,
       w.total_ratings,
       ROUND(w.prior_20, 2)             AS prior_20_avg,
       ROUND(w.last_20, 2)              AS last_20_avg,
       ROUND(w.last_20 - w.prior_20, 2) AS delta
  FROM windows w
 WHERE w.last_20 - w.prior_20 <= -0.5
 ORDER BY delta;
