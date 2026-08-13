# UUIDv7 documentation cleanup design

## Goal

Leave PR #833 with only durable UUIDv7 guidance. Remove completed planning
records and unrelated formatting churn instead of preserving implementation
history as maintainer documentation.

This temporary design record and its implementation plan are execution
artifacts and will be removed by the cleanup they describe.

## Changes

- Delete the completed UUIDv7 foundation design and implementation plan.
- Delete the completed PostgreSQL-only cleanup plan.
- Match the older one-time SQLite-to-PostgreSQL cutover plan to current
  `origin/main`, where it has been deleted.
- Compress the README identifier convention to the field, route converter,
  and warning that UUID time/order is not business chronology.
- Compress deployment guidance to generic-tool casting and the operational
  clock-skew warning contract.

## Boundaries

Historical changelog entries and unrelated PostgreSQL design/plan records stay
unchanged. Runtime behavior, migrations, tests, and public interfaces do not
change.

## Acceptance

The final diff contains no completed #639 planning artifacts, no unrelated
cutover-plan formatting changes, and concise permanent guidance that agrees
with the implemented UUIDv7 field, converter, domain, and clock warning.
