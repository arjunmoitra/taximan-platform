"""Optional Snowflake analytics layer.

MySQL stays the system of record. This package copies an allowlisted, PII free
subset of it to Snowflake as typed Parquet, builds the analytical views there,
and reconciles the copy against the source. Install with
`pip install -e ".[warehouse]"`.
"""
