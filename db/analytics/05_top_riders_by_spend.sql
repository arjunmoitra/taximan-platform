-- Q05 Top riders by lifetime spend with their share of total revenue and a
-- running cumulative share (Pareto view). Window functions over an aggregate.
WITH spend AS (
    SELECT t.rider_id, COUNT(*) AS trips, SUM(p.amount_cents) AS spent_cents
      FROM trips t
      JOIN payments p ON p.trip_id = t.id AND p.status = 'captured'
     GROUP BY t.rider_id
)
SELECT ROW_NUMBER() OVER (ORDER BY s.spent_cents DESC)                                  AS rnk,
       u.full_name,
       z.name                                                                           AS home_zone,
       s.trips,
       ROUND(s.spent_cents / 100, 2)                                                    AS spent_dollars,
       ROUND(100 * s.spent_cents / SUM(s.spent_cents) OVER (), 3)                       AS pct_of_revenue,
       ROUND(100 * SUM(s.spent_cents) OVER (ORDER BY s.spent_cents DESC) / SUM(s.spent_cents) OVER (), 2) AS cumulative_pct
  FROM spend s
  JOIN riders r ON r.user_id = s.rider_id
  JOIN users u  ON u.id = r.user_id
  LEFT JOIN zones z ON z.id = r.home_zone_id
 ORDER BY rnk
 LIMIT 20;
