# Timetracker

A simple game catalogue and play session tracker.

# Development

Nix is the supported development environment. Enter it with `nix-shell` (or
direnv), then run:

```
make init
```

This initializes an ignored, loopback-only PostgreSQL cluster under `.cache/`,
syncs dependencies, and installs npm packages. `make` automatically reuses that
cluster. Outside Nix, it downloads the project-pinned PostgreSQL binary for
supported platforms; alternatively set `DATABASE_URL` to an existing database.
The local cluster is disposable.
Afterwards, you can start the development server using `make dev` or `make server`
(without the Tailwind watcher). Both targets accept `DEV_HOST` and `DEV_PORT`, for
example `make dev DEV_HOST=0.0.0.0 DEV_PORT=9999`.

## Identifier convention

New Timetracker domain/catalog identities use `timetracker.uuidv7.UUIDv7Field`.
It assigns Python's `uuid.uuid7()` before save and maps to PostgreSQL's
`uuid_v7` domain, whose column fallback is `uuidv7()`. Use the
`<uuidv7:identifier>` route converter for untrusted URL identifiers.
Django-owned framework tables retain their existing key types.

UUID order is approximately chronological. The embedded time is diagnostic
metadata and never replaces an explicit creation time, business date, or event
sequence.

# Running the image

`registry.kucharczyk.xyz/timetracker` tags: `latest` (moves with main),
`main-<sha>` (immutable, pinnable), `vX.Y.Z` (releases).

The container runs as uid 1000. Mounted data directories must be writable
by that uid.

See the [database contract](docs/database.md) for PostgreSQL requirements and
[Deployment](docs/deployment.md) for Docker Compose and rootless Podman Quadlet
examples.

Health probes: `/health` (liveness), `/health/ready` (adds a database
check). Both answer without auth or a Host header.
