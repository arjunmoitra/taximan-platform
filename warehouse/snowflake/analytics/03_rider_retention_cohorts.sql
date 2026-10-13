-- Port of db/analytics/03_rider_retention_cohorts.sql
-- Changes: cohort_month stays a DATE instead of a '%Y-%m-01' string.
-- DATEDIFF('month', ...) counts calendar month boundaries, TIMESTAMPDIFF(MONTH)
-- counts whole elapsed months. They agree here because cohort_month is always
-- the first day of a month at midnight.
CREATE OR REPLACE VIEW analytics.q03_rider_retention_cohorts AS
WITH first_month AS (
    SELECT r.user_id,
           CAST(DATE_TRUNC('month', r.created_at) AS DATE) AS cohort_month
      FROM raw.riders r
     CROSS JOIN analytics.as_of a
     WHERE r.created_at >= DATEADD('month', -12, a.as_of)
),
activity AS (
    SELECT t.rider_id,
           DATEDIFF('month', f.cohort_month, t.requested_at) AS months_since_signup
      FROM raw.trips t
      JOIN first_month f ON f.user_id = t.rider_id
     WHERE t.status = 'completed'
)
SELECT f.cohort_month,
       COUNT(DISTINCT f.user_id)                                              AS cohort_size,
       ROUND(100 * COUNT(DISTINCT CASE WHEN a.months_since_signup = 0 THEN a.rider_id END) / COUNT(DISTINCT f.user_id), 1) AS m0_pct,
       ROUND(100 * COUNT(DISTINCT CASE WHEN a.months_since_signup = 1 THEN a.rider_id END) / COUNT(DISTINCT f.user_id), 1) AS m1_pct,
       ROUND(100 * COUNT(DISTINCT CASE WHEN a.months_since_signup = 2 THEN a.rider_id END) / COUNT(DISTINCT f.user_id), 1) AS m2_pct,
       ROUND(100 * COUNT(DISTINCT CASE WHEN a.months_since_signup = 3 THEN a.rider_id END) / COUNT(DISTINCT f.user_id), 1) AS m3_pct
  FROM first_month f
  LEFT JOIN activity a ON a.rider_id = f.user_id
 GROUP BY f.cohort_month
 ORDER BY f.cohort_month;
