-- Port of db/analytics/06_driver_rating_shrinkage.sql
-- Changes: drivers are identified by driver_id. Ratios are DOUBLE so ranks do not depend on
-- an engine's decimal division scale (see the MySQL original).
CREATE OR REPLACE VIEW analytics.q06_driver_rating_shrinkage AS
WITH global_stats AS (
    SELECT CAST(SUM(rating_sum) AS DOUBLE) / SUM(rating_count) AS mu
      FROM raw.drivers
     WHERE rating_count > 0
)
SELECT d.user_id                                                                  AS driver_id,
       d.rating_count,
       ROUND(CAST(d.rating_sum AS DOUBLE) / d.rating_count, 3)                    AS raw_avg,
       ROUND((d.rating_sum + 20 * g.mu) / (d.rating_count + 20), 3)               AS shrunk_avg,
       RANK() OVER (ORDER BY (d.rating_sum + 20 * g.mu) / (d.rating_count + 20) DESC) AS shrunk_rank,
       RANK() OVER (ORDER BY CAST(d.rating_sum AS DOUBLE) / d.rating_count DESC)  AS raw_rank
  FROM raw.drivers d
 CROSS JOIN global_stats g
 WHERE d.rating_count > 0
 ORDER BY shrunk_rank;
