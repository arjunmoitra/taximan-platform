-- Port of db/analytics/05_top_riders_by_spend.sql
-- Changes: riders are identified by rider_id. rider_id is the tie-breaker in
-- ROW_NUMBER so equal spenders always get the same rank.
CREATE OR REPLACE VIEW analytics.q05_top_riders_by_spend AS
WITH spend AS (
    SELECT t.rider_id, COUNT(*) AS trips, SUM(p.amount_cents) AS spent_cents
      FROM raw.trips t
      JOIN raw.payments p ON p.trip_id = t.id AND p.status = 'captured'
     GROUP BY t.rider_id
)
SELECT ROW_NUMBER() OVER (ORDER BY s.spent_cents DESC, s.rider_id)                      AS rnk,
       s.rider_id,
       z.name                                                                           AS home_zone,
       s.trips,
       ROUND(s.spent_cents / 100, 2)                                                    AS spent_dollars,
       ROUND(100 * s.spent_cents / SUM(s.spent_cents) OVER (), 3)                       AS pct_of_revenue,
       ROUND(100 * SUM(s.spent_cents) OVER (ORDER BY s.spent_cents DESC) / SUM(s.spent_cents) OVER (), 2) AS cumulative_pct
  FROM spend s
  JOIN raw.riders r     ON r.user_id = s.rider_id
  LEFT JOIN raw.zones z ON z.id = r.home_zone_id
 ORDER BY rnk;
