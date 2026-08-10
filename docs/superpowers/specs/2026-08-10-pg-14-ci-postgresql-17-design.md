# PG-14: PostgreSQL 17 CI verification

Date: 2026-08-10

Related issue: https://github.com/KucharczykL/timetracker/issues/616

## Outcome

Run the existing GitHub Actions verification gate against an explicit
PostgreSQL 17 server that satisfies the project database contract.

## Design

The `test` job in `build-docker.yml` declares a `postgres:17` service.  It
creates an ephemeral `timetracker` database for a CI-only superuser and passes
the matching `DATABASE_URL` to the unchanged `make check` command.  The server
initializes with UTF8, PostgreSQL's `builtin` locale provider, and builtin
locale `C.UTF-8`; its health check gates the job until it accepts connections.

`ensure-postgres` already treats an explicit `DATABASE_URL` as authoritative,
so CI will not download or start the developer fallback cluster.  Django's
existing connection-created validation proves the actual service major,
encoding, provider, and locale during test-database use.

## Scope and reversibility

This issue changes only the CI test job and its regression coverage.  It does
not change the Makefile interface or worker policy, Compose deployment,
backups, transfer, or runtime configuration.  Removing the workflow service
and job URL restores the previous fallback behavior; no persistent data exists
in the Actions service.

## Verification

A focused test parses the workflow and asserts the service image, database
contract initialization, health check, and job URL wiring.  The complete
`make check` gate remains the end-to-end proof: it creates and uses PostgreSQL
test databases, whose startup validation rejects a nonconforming server.
