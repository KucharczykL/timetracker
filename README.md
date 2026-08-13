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

## Identifiers

Use `timetracker.uuidv7.UUIDv7Field` for new Timetracker identifiers and
`<uuidv7:identifier>` for URL parameters. UUIDv7 time and ordering are
diagnostic metadata, not creation times, business dates, or event sequences.

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
