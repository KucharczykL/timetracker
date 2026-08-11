# Timetracker

A simple game catalogue and play session tracker.

# Development

Nix is the supported development environment: it supplies PostgreSQL 18,
Python, Node, and the other project tools. Enter it with `nix-shell` (or
direnv), then run:

```
make init
```

This initializes an ignored, loopback-only PostgreSQL 18 cluster under `.cache/`,
syncs dependencies, and installs npm packages. `make` automatically reuses that
cluster. Outside Nix, `make` uses a checksum-pinned PostgreSQL 18.4 binary fallback
for supported platforms; alternatively set `DATABASE_URL` to an existing database.
If you previously ran the PostgreSQL 17 harness, stop it, remove only
`.cache/postgres/data`, then run `make` again. The local cluster is disposable;
do not start its PostgreSQL 17 data directory with PostgreSQL 18.
Afterwards, you can start the development server using `make dev` or `make server`
(without the Tailwind watcher). Both targets accept `DEV_HOST` and `DEV_PORT`, for
example `make dev DEV_HOST=0.0.0.0 DEV_PORT=9999`.

# Running the image

`registry.kucharczyk.xyz/timetracker` tags: `latest` (moves with main),
`main-<sha>` (immutable, pinnable), `vX.Y.Z` (releases).

The container runs as uid 1000. Mounted data directories must be writable
by that uid.

## Docker

```
docker run -d --name timetracker \
  -e SECRET_KEY=change-me \
  -e APP_URL=http://localhost:8000 \
  -v ./data:/home/timetracker/app/data \
  -p 8000:8000 \
  registry.kucharczyk.xyz/timetracker:latest
```

## Rootless Podman (quadlet)

`~/.config/containers/systemd/timetracker.container`:

```ini
[Container]
Image=registry.kucharczyk.xyz/timetracker:latest
PublishPort=8000:8000
Environment=SECRET_KEY=change-me
Environment=APP_URL=http://localhost:8000
Volume=%h/timetracker/data:/home/timetracker/app/data
# keep-id maps the host uid onto the container user (overrides image USER)
UserNS=keep-id:uid=1000

[Install]
WantedBy=default.target
```

Health probes: `/health` (liveness), `/health/ready` (adds a database
check). Both answer without auth or a Host header.
