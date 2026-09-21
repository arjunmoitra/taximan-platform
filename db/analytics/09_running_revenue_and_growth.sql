-- Q09 Daily captured revenue with running total and week over week growth.
-- Window SUM for the cumulative and LAG for the comparison.
WITH daily AS (
    SELECT DATE(p.captured_at) AS day, SUM(p.amount_cents) AS revenue_cents, COUNT(*) AS payments
      FROM payments p
     WHERE p.status = 'captured'
       AND p.captured_at >= UTC_TIMESTAMP() - INTERVAL 60 DAY
     GROUP BY DATE(p.captured_at)
)
SELECT day,
       payments,
       ROUND(revenue_cents / 100, 2)                                                         AS revenue_dollars,
       ROUND(SUM(revenue_cents) OVER (ORDER BY day) / 100, 2)                                AS cumulative_dollars,
       ROUND(AVG(revenue_cents) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) / 100, 2) AS rolling_7d_avg,
       ROUND(100 * (revenue_cents - LAG(revenue_cents, 7) OVER (ORDER BY day)) / LAG(revenue_cents, 7) OVER (ORDER BY day), 1) AS wow_growth_pct
  FROM daily
 ORDER BY day;
