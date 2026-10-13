-- One-time setup. Idempotent, so it is safe to run again.
-- Run it with a role that may create a warehouse and a database (SYSADMIN is
-- enough). The loader itself needs nothing more than USAGE on the warehouse and
-- CREATE TABLE / CREATE VIEW / CREATE STAGE on the two schemas.

-- XSMALL with a 60 second auto suspend: the warehouse bills per second of run
-- time while it is awake, so a full reload uses a small fraction of a credit.
-- INITIALLY_SUSPENDED means creating it costs nothing.
CREATE WAREHOUSE IF NOT EXISTS taximan_wh
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Taximan analytics loads and queries';

CREATE DATABASE IF NOT EXISTS taximan;
CREATE SCHEMA IF NOT EXISTS taximan.raw;        -- typed copies of the OLTP tables, no PII
CREATE SCHEMA IF NOT EXISTS taximan.analytics;  -- views the BI layer reads

-- USE_LOGICAL_TYPE makes Snowflake read Parquet timestamps and decimals by their
-- logical type instead of as raw integers. `taximan warehouse check` compares
-- row counts, sums and min / max timestamps with MySQL, so a mistake here shows
-- up as a failed reconciliation rather than as quietly wrong numbers.
CREATE FILE FORMAT IF NOT EXISTS taximan.raw.taximan_parquet
    TYPE = PARQUET
    USE_LOGICAL_TYPE = TRUE;

CREATE STAGE IF NOT EXISTS taximan.raw.taximan_stage
    FILE_FORMAT = taximan.raw.taximan_parquet
    COMMENT = 'Parquet extracts written by `taximan warehouse extract`';
