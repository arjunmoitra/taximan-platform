-- Port of db/analytics/12_zone_flow_matrix.sql
-- Changes: QUALIFY keeps the top 3 destinations per origin without the extra
-- CTE and outer WHERE, and the final SELECT lists its columns.
CREATE OR REPLACE VIEW analytics.q12_zone_flow_matrix AS
WITH flows AS (
    SELECT pz.name                         AS from_zone,
           dz.name                         AS to_zone,
           COUNT(*)                        AS trips,
           AVG(t.distance_km)              AS avg_km_raw,
           AVG(t.fare_cents)               AS avg_fare_cents_raw
      FROM raw.trips t
      JOIN raw.zones pz ON pz.id = t.pickup_zone_id
      JOIN raw.zones dz ON dz.id = t.dropoff_zone_id
     CROSS JOIN analytics.as_of a
     WHERE t.status = 'completed'
       AND t.completed_at >= DATEADD('day', -30, a.as_of)
     GROUP BY pz.name, dz.name
)
SELECT from_zone,
       to_zone,
       trips,
       ROUND(100 * trips / SUM(trips) OVER (PARTITION BY from_zone), 1) AS pct_of_origin,
       ROUND(avg_km_raw, 2)                                              AS avg_km,
       ROUND(avg_fare_cents_raw / 100, 2)                                AS avg_fare_dollars,
       RANK() OVER (PARTITION BY from_zone ORDER BY trips DESC)          AS rank_within_origin
  FROM flows
QUALIFY rank_within_origin <= 3
 ORDER BY from_zone, rank_within_origin;
