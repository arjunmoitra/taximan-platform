-- Port of db/analytics/09_running_revenue_and_growth.sql
-- Unchanged apart from the anchor and DATE casts.
CREATE OR REPLACE VIEW analytics.q09_running_revenue_and_growth AS
WITH daily AS (
    SELECT CAST(p.captured_at AS DATE) AS day, SUM(p.amount_cents) AS revenue_cents, COUNT(*) AS payments
      FROM raw.payments p
     CROSS JOIN analytics.as_of a
     WHERE p.status = 'captured'
       AND p.captured_at >= DATEADD('day', -60, a.as_of)
     GROUP BY CAST(p.captured_at AS DATE)
)
SELECT day,
       payments,
       ROUND(revenue_cents / 100, 2)                                                         AS revenue_dollars,
       ROUND(SUM(revenue_cents) OVER (ORDER BY day) / 100, 2)                                AS cumulative_dollars,
       ROUND(AVG(revenue_cents) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) / 100, 2) AS rolling_7d_avg,
       ROUND(100 * (revenue_cents - LAG(revenue_cents, 7) OVER (ORDER BY day)) / LAG(revenue_cents, 7) OVER (ORDER BY day), 1) AS wow_growth_pct
  FROM daily
 ORDER BY day;
