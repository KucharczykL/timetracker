# External PostgreSQL deployment and recovery delivery design

## Outcome

Deliver the remaining work from #617 and #618 as one sequential plan: first
publish and verify the external PostgreSQL 18 deployment contract, then publish
and verify manual backup and isolated restore procedures.

## Scope and sequencing

### Stage 1: External deployment (#617)

Replace the incomplete Docker and rootless Podman Quadlet examples with an
app-only deployment guide. The guide uses one complete PostgreSQL 18 URL via
`DATABASE_URL__FILE`; it never defines a PostgreSQL service, volume, server
configuration, or lifecycle.

The rootless Quadlet example connects Timetracker to an operator-managed
`backend.network`, mounts the URL secret read-only, and uses `postgres` only as
an illustrative network alias. It preserves the image's uid 1000 / `keep-id`
permission model: the host secret must be readable by the mapped host user.

The Docker example uses the same file-backed secret contract. Both examples
state that operators may use any maintained PostgreSQL 18.x server, while the
project fallback and CI service are pinned to 18.4.

### Verification gate

Before backup work begins, tests parse the Compose deployment, check the
operator guide's bounded contract, and require the image-user secret smoke-test
workflow step. GitHub Actions provides the actual Docker execution evidence.
The stage passes only when the full local `make check` gate passes and the
workflow remains pinned to `postgres:18.4`.

### Stage 2: Manual backup and isolated restore (#618)

Extend the same guide with a manual database-only custom-format backup command
using PostgreSQL-18-compatible client tools and:

```text
pg_dump --format=custom --no-owner --no-privileges
```

Document an isolated restore check: an administrator creates a deliberately
named empty verification database, `pg_restore --exit-on-error` restores the
dump with ownership and privilege restoration disabled, and Timetracker runs a
read-only migration/schema check against that database. Success drops only the
verification database. Failure leaves it for inspection; it never drops,
recreates, or replaces the live database.

GitHub Actions repeats that bounded dump/restore flow against its
`postgres:18.4` service. The backup file is CI-disposable and the verification
database name is fixed and explicit. The cleanup trap may target only that
verification database.

## Non-goals

- Bundled PostgreSQL deployment or server management.
- Discrete database host/user/password settings.
- Backup scheduling, retention, monitoring, alerting, or off-host transport
  (these remain #597).
- Automated or routine destructive production recovery.

## Verification

Stage 1 is independently verified before Stage 2 changes begin. The final
gate runs the full `make check`; CI subsequently executes both the container
secret smoke test and PostgreSQL 18.4 dump/restore proof.
