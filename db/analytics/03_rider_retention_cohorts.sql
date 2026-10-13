-- Q03 Rider retention by signup month cohort.
-- Classic cohort table: for each signup month, what share of riders took a
-- trip 1, 2, 3 months after signup. CTEs + conditional aggregation.
WITH first_month AS (
    SELECT r.user_id,
           DATE_FORMAT(r.created_at, '%Y-%m-01') AS cohort_month
      FROM riders r
     WHERE r.created_at >= UTC_TIMESTAMP() - INTERVAL 12 MONTH
),
activity AS (
    SELECT t.rider_id,
           -- Calendar months, not TIMESTAMPDIFF(MONTH): that truncates toward zero, so a trip up to
           -- a month before the cohort month would be counted as month 0. PERIOD_DIFF is signed.
           PERIOD_DIFF(EXTRACT(YEAR_MONTH FROM t.requested_at),
                       EXTRACT(YEAR_MONTH FROM f.cohort_month)) AS months_since_signup
      FROM trips t
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
