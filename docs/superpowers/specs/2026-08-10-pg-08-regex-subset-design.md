# PG-08: PostgreSQL-native regex filters

## Decision

PostgreSQL's regular-expression dialect is the product contract. The application
does not define a second, supposedly portable language and does not parse regex
syntax itself.

## Validation and execution

`StringCriterion` retains a 200-character limit and requires a string value for
regex modifiers. It asks PostgreSQL to compile each submitted pattern through a
parameterized expression against an empty string. PostgreSQL syntax error
`2201B` becomes the existing `FilterError` boundary, so saved presets, HTML
filters, and APIs reject invalid patterns before storing or evaluating them.

The actual matching query is still parameterized through Django's `__regex`
lookup. Regex-bearing list and API requests retain the transaction-local
one-second PostgreSQL `statement_timeout` from PG-09; that is the resource
bound, not a syntax heuristic.

## Consequences

Python `re` compatibility, the handwritten grammar, and private CPython regex
AST use are removed. Existing filters use PostgreSQL syntax after the runtime
cutover. The user removed the only production saved presets, so no preset data
migration or reconciliation is required.

## Verification

Tests cover PostgreSQL-valid syntax that the former subset rejected, invalid
PostgreSQL syntax mapped to `FilterError`, saved-filter parsing, and the
existing timeout and actual ORM matching paths. Reverting this code restores
the former validator; no database schema or data is changed.
