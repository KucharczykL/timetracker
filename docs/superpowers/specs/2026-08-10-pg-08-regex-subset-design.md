# PG-08: Portable regex subset

Regex filters accept only documented cross-engine syntax; unsupported syntax is rejected at parse time. Verification includes parser tables and PostgreSQL ORM matching. Reverting restores the former validator.
