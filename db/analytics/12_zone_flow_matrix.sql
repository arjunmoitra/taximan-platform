-- Q12 Origin destination flow between zones with each pair's share of the
-- origin's outbound trips. Self join of zones through trips, window by origin,
-- top 3 destinations per origin.
WITH flows AS (
    SELECT pz.name                                                    AS from_zone,
           dz.name                                                    AS to_zone,
           COUNT(*)                                                   AS trips,
           ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY pz.name), 1) AS pct_of_origin,
           ROUND(AVG(t.distance_km), 2)                               AS avg_km,
           ROUND(AVG(t.fare_cents) / 100, 2)                          AS avg_fare_dollars,
           RANK() OVER (PARTITION BY pz.name ORDER BY COUNT(*) DESC)  AS rank_within_origin
      FROM trips t
      JOIN zones pz ON pz.id = t.pickup_zone_id
      JOIN zones dz ON dz.id = t.dropoff_zone_id
     WHERE t.status = 'completed'
       AND t.completed_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
     GROUP BY pz.name, dz.name
)
SELECT *
  FROM flows
 WHERE rank_within_origin <= 3
 ORDER BY from_zone, rank_within_origin;
