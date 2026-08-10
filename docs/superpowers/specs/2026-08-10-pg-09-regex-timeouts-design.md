# PG-09: Regex query timeouts

Regex-bearing requests run with a transaction-local one-second PostgreSQL statement timeout. Timeout errors become HTML recovery or API 400 responses; unrelated database errors propagate. Verification uses `pg_sleep` and timeout-reset tests.
