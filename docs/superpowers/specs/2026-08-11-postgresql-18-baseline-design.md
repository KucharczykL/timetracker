# PostgreSQL 18 baseline design

## Outcome

Make PostgreSQL major 18 Timetracker's single supported runtime baseline while
pinning project-controlled development and CI tooling to PostgreSQL 18.4.

## Contract

- Runtime accepts PostgreSQL `18.x` and rejects PostgreSQL 17, 19, and every
  other major version.
- The existing UTF8, `builtin`, and `C.UTF-8` database contract is unchanged.
- `timetracker.postgres_contract` exposes one public runtime constant,
  `REQUIRED_POSTGRES_MAJOR = 18`.
- `scripts/ensure_postgres.py` imports that major constant. Its separate
  `FALLBACK_VERSION = "18.4.0"` identifies exact downloaded archives only.
- GitHub Actions uses the PostgreSQL patch-version pin `postgres:18.4`.
  Production operators may use any maintained PostgreSQL 18 minor release.

## Fallback assets

The checksum-pinned fallback changes to PostgreSQL 18.4.0 for the existing
platform set. Tests assert the complete mapping, not only the platform that
executes a given local test run:

| Platform | Archive | SHA-256 |
| --- | --- | --- |
| Linux x86_64 | `postgresql-18.4.0-x86_64-unknown-linux-gnu.tar.gz` | `65c06cf318b9a57525d842d658d6d18cd461d12b3a89b57d6d8ed7cccbe2db53` |
| macOS arm64 | `postgresql-18.4.0-aarch64-apple-darwin.tar.gz` | `1b68828f524b638a24918e258b173d0f16773547a0d3b83d9ba74473b61649f2` |
| macOS x86_64 | `postgresql-18.4.0-x86_64-apple-darwin.tar.gz` | `cbc38067a795d10bbddc730e61c835df0b351c36a7bd2544d388790fcf50aa4d` |
| Windows x86_64 | `postgresql-18.4.0-x86_64-pc-windows-msvc.tar.gz` | `4099dcf71c74bed82736e17928d07591df0efee8f802449533b9557d99ae7988` |

## Reversibility and verification

PostgreSQL 17 developer clusters are disposable cache state and must not be
started with PostgreSQL 18. The upgrade note tells developers to stop the local
harness, remove only `.cache/postgres/data`, and run `make` again; PostgreSQL 18
then initializes a new cluster. No cache migration, versioned cache path, or
automatic deletion is introduced.

Unit tests accept a PostgreSQL 18 catalog snapshot and reject 17 and 19.
Fallback tests pin the exact 18.4.0 archives. CI tests pin `postgres:18.4`.
`shell.nix` supplies `postgresql_18`; only the fallback and CI use the 18.4
patch pin. A fresh Windows `make check` proves fallback download, cluster
initialization, runtime contract validation, and the full suite.

Both Compose deployments retain the existing app-only `DATABASE_URL__FILE`
secret contract. Add a non-root container smoke test for that mounted secret,
or an equivalent test that proves the UID 1000 image user can read it; do not
assume a file-backed Compose secret applies `mode: 0400` ownership semantics.

## Scope

Update runtime, fallback harness, Nix shell, CI, tests, and PostgreSQL-version
documentation. Amend the existing external-PostgreSQL design and implementation
plan to replace their dual-major contract and CI matrix with this one-major
baseline, preserving their `DATABASE_URL__FILE` and app-only Compose work.
#617's external-PostgreSQL deployment boundary remains intact; #618's manual
backup/restore scope is unchanged, except its CI proof uses PostgreSQL 18.4.
