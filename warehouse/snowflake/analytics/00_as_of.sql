-- The reference time for every "last N days" window in the views below.
--
-- The MySQL originals use UTC_TIMESTAMP(), so their answer changes every time
-- they run. A warehouse view over a snapshot should not: it anchors on the
-- latest request in the data, so a reload of the same extract gives the same
-- numbers whenever it is queried. Against live, continuously loaded data this
-- would become CURRENT_TIMESTAMP().
CREATE OR REPLACE VIEW analytics.as_of AS
SELECT MAX(requested_at) AS as_of
  FROM raw.trips;
