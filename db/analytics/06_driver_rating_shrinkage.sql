-- Q06 Driver ratings with Bayesian shrinkage.
-- A driver with two 5 star ratings should not outrank one with 400 ratings
-- averaging 4.8. Shrink toward the global mean with a prior weight of 20.
WITH global_stats AS (
    -- Ratios are computed as DOUBLE. MySQL's DECIMAL division keeps 4 digits, which turned
    -- 29 distinct driver averages into ties and shifted the ranks.
    SELECT CAST(SUM(rating_sum) AS DOUBLE) / SUM(rating_count) AS mu FROM drivers WHERE rating_count > 0
)
SELECT u.full_name,
       d.rating_count,
       ROUND(CAST(d.rating_sum AS DOUBLE) / d.rating_count, 3)                    AS raw_avg,
       ROUND((d.rating_sum + 20 * g.mu) / (d.rating_count + 20), 3)               AS shrunk_avg,
       RANK() OVER (ORDER BY (d.rating_sum + 20 * g.mu) / (d.rating_count + 20) DESC) AS shrunk_rank,
       RANK() OVER (ORDER BY CAST(d.rating_sum AS DOUBLE) / d.rating_count DESC)  AS raw_rank
  FROM drivers d
  JOIN users u ON u.id = d.user_id
  CROSS JOIN global_stats g
 WHERE d.rating_count > 0
 ORDER BY shrunk_rank
 LIMIT 20;
