# Rootless-native Docker image (issue #566)

Date: 2026-07-28
Issue: https://github.com/KucharczykL/timetracker/issues/566

## Goal

The NAS deployment moved to a rootless Podman quadlet. The image currently
*requires* starting as root (`User=0:0` + `UserNS=keep-id:uid=%U,gid=%G`)
purely because `entrypoint.sh` unconditionally runs
`usermod`/`groupmod`/`chown` under `set -e`. Make the image rootless-native:
no root anywhere, meaningful health probe, immutable image tags, and
documented run instructions.

Decision: **full non-root**, not a dual-path guard. The PUID/PGID remap
machinery is deleted outright. Foreclosed: root-docker deployments with host
data owned by uid≠1000 lose the in-container remap escape hatch (they must
chown the host dir or use `--user`/keep-id). Both real consumers (NAS quadlet,
staging) are uid 1000; the remap served only the pattern being left.

**uid/gid nuance (both paths, stated once):** podman's `keep-id` *overrides*
the image's `USER` directive — on the NAS the process runs 1000:**100**
(host `lukas:users` via `keep-id:uid=%U,gid=%G`) regardless of `USER`. Plain
`docker run` uses the image default and runs 1000:**1000**
(`timetracker:timetracker`). Both are owner-writable everywhere that matters
(`COPY --chown` + `useradd -m` make uid 1000 the owner of the app tree,
`$HOME`, and the pre-created data dir); the gid difference only shows in the
group of newly written files. `USER timetracker` therefore governs the docker
path and is inert-but-harmless under keep-id.

## 1. Dockerfile + entrypoint + supervisor

- **Dockerfile**: add `USER timetracker` before `ENTRYPOINT`. Pre-create
  `/home/timetracker/app/data` owned `timetracker:timetracker` (correct
  default ownership for fresh named-volume copy-up and a sane in-image
  default), and **remove the stale `mkdir /home/timetracker/data`** — wrong
  path, nothing uses it (the `DATA_DIR` default everywhere is
  `/home/timetracker/app/data`). Drop `libcap2-bin` (verified: no `setcap`
  anywhere, both ports >1024). Drop `/var/log/supervisor` creation — every
  supervised program logs to `/dev/stdout|stderr`, nothing writes there
  (supervisord's pidfile lands in `$CWD`, childlogdir defaults to `/tmp`).
  Add `HEALTHCHECK` probing `/health` (see §2).
- **entrypoint.sh**: delete `PUID`/`PGID` vars, `usermod`/`groupmod`, every
  `chown`/`chmod` line, and the `/var/log/supervisor` mkdir. Keep
  `mkdir -p "$DATA_DIR"`, migrate, collectstatic, the
  `STAGING`/`LOAD_SAMPLE_DATA`/`CREATE_DEFAULT_SUPERUSER` blocks, and
  `exec supervisord`. Everything runs as uid 1000 start to finish, including
  migrate/collectstatic (today they run as root).
- **supervisor.conf**: remove every `user=` key (including
  `[supervisord] user=root`). One conf, no per-program user switching —
  supervisord and all programs already share one uid.

### PUID/PGID removal touches every reference, not just the entrypoint

- `docker-compose.yml`: drop the `PUID`/`PGID` environment lines.
- `.env.example`: drop `PUID`/`PGID`.
- `docs/configuration.md`: remove the PUID/PGID row from the
  container-bootstrap table; note the uid-1000 ownership requirement instead.
- `CLAUDE.md`: update the container-bootstrap flag list (PUID/PGID gone).
- `.gitea/workflows/staging.yml`: drop the now-inert `-e PUID=1000
  -e PGID=100` flags.

### Staging seed step must chown the volume directory (blocker fix)

Docker named-volume copy-up only happens into an **empty** volume.
`staging.yml` creates the volume and seeds `db.sqlite3` into it from a root
container *before* the app container ever starts — so copy-up never fires,
the volume dir stays `root:root`, and today only the entrypoint's root
`chown` papers over it. With the chowns deleted, uid 1000 could not create
the WAL/SHM sidecar files and the entrypoint would die on `migrate`.

Fix in the same seed step: `chown -R 1000:100 /dest` (directory, not just
the db file — it currently chowns only the file). This is the one place a
root-capable container legitimately remains (the seed helper, not the app
image).

## 2. Health endpoints

- New middleware in `common/middleware.py` (beside
  `TimezoneActivationMiddleware`), placed **first** in `MIDDLEWARE`:
  `/health` → 200 `ok` (liveness, no DB); `/health/ready` → `SELECT 1` →
  200, else 503 (readiness). Middleware rather than URLconf because host
  validation happens in middleware (`CommonMiddleware.process_request` calls
  `get_host()`) before URL routing is ever reached — a URLconf view could
  never answer a bare-IP probe. Short-circuiting first in the chain means
  `curl -f http://127.0.0.1:8000/health` works with no `Host:` header hack
  and no auth. (Verified: the ASGI handler itself never calls `get_host()`;
  `SecurityMiddleware` only under `SECURE_SSL_REDIRECT`, unset here.)
- Dockerfile `HEALTHCHECK` uses `/health` (liveness) with explicit
  parameters matching the quadlet's current probe timing:
  `--interval=30s --timeout=5s --start-period=30s --retries=5` (default
  `start-period=0` would flap unhealthy while first-start
  migrate/collectstatic/seed still runs). Restarting the container never
  fixes a busy SQLite, so the restart-triggering probe stays DB-free;
  `/health/ready` exists for runtimes that want the deeper check.
- Caddy's catch-all `reverse_proxy` already forwards both paths (verified:
  only `/static/*` and `/robots.txt` are intercepted); gunicorn binds 8001.
- Tests: bogus `Host:` header still 200; unauthenticated 200 (no login
  redirect); `/health/ready` 503 when the DB connection fails (mocked);
  normal requests unaffected by the middleware.

## 3. Immutable image tags

Applies to **both** `.github/workflows/build-docker.yml` and
`.gitea/workflows/build.yml`. They push the same tag list today but are
otherwise different files (Node versions, test steps) — apply the tag change
to each respectively, not by copy-paste.

- Per main merge: push `latest` + immutable `main-<short-sha>` (rollback/pin
  target). Delete the `VERSION_NUMBER` tag push and the "Set Version" step.
- **New separate workflow file** per forge (e.g. `release-image.yml`) with
  `on: push: tags: ['v[0-9]+.[0-9]+.[0-9]+']`. It must NOT be added to the
  existing workflows' `on: push` — a `tags:` filter on a push trigger with
  no `branches:` filter stops the workflow running on branch pushes
  entirely, killing CI. Releases switch to `vX.Y.Z` naming from here on; the
  20 historical bare tags (`0.1.0`–`1.3.0`) never match the pattern.
- The release workflow retags the already-built `main-<short-sha>` of the
  tagged commit as `timetracker:<tag>` (verbatim, e.g.
  `timetracker:v1.8.0` — no prefix-stripping logic) via
  `docker buildx imagetools create` — no rebuild, version tag minted exactly
  once → immutable. Registry auth: none needed — verified the registry
  accepts anonymous access (that is also how today's login-step-less pushes
  work). If the tag is pushed before the main-merge build finished, the
  retag fails; rerun the job (acceptable — releases are cut from
  already-built main commits).
- Release process (manual, when ready; note versions 1.4–1.7 were never
  git-tagged, this revives the habit): bump version in `pyproject.toml` +
  Dockerfile `ENV VERSION_NUMBER`, merge, `git tag vX.Y.Z && git push origin
  vX.Y.Z`, `gh release create vX.Y.Z --generate-notes` (GitHub) / `tea
  release create --tag vX.Y.Z` (Gitea).

## 4. README

New "Running the image" section:

- `docker run` example: data volume mount, `SECRET_KEY`, port 8000. Note the
  container runs as uid 1000 — the host data dir must be writable by it.
- Rootless Podman: quadlet snippet with `UserNS=keep-id:uid=1000` and a note
  that keep-id overrides the image's `USER` (no `User=` needed either way —
  the image default user is already non-root).
- Health endpoints (`/health`, `/health/ready`) and tag scheme (`latest`
  moves, `main-<sha>` immutable, `vX.Y.Z` minted on release tags).

## 5. Deployment rollout (post-merge, other repo)

In `~/git/docker-compose-templates` after the image PR merges and CI pushes:

- Quadlet `quadlet/timetracker.container`: drop `User=0:0`, keep
  `UserNS=keep-id:uid=%U,gid=%G` (as it reads today), drop the
  `PUID`/`PGID` `Environment=` lines, `HealthCmd` →
  `curl -sf http://127.0.0.1:8000/health` (Host-header hack gone), update
  the header comment (root-then-drop description obsolete), note the
  `main-<sha>` pin option. `secrets/dot-env` keeps its `PUID`/`PGID`
  definitions (other containers use them); only this quadlet stops
  referencing them.
- `ssh nas`: pull, `systemctl --user daemon-reload && systemctl --user
  restart timetracker`; verify process uid is 1000 (host-side `lukas`),
  health status `healthy`, site reachable. This step is the real
  verification of the keep-id path (the local smoke test in §6 exercises
  only the docker path).

## 6. Verification

- Full `make check` (the repo gate) before PR.
- Local image smoke test, both uid paths:
  - `docker/podman run` with **no** user flags: entrypoint completes
    (migrate + collectstatic), supervisord starts all three programs,
    `/health` 200, `/health/ready` 200, `id -u` = 1000 (image `USER` path).
  - `podman run --userns=keep-id:uid=1000,gid=100` (or `--user 1000:100`):
    same checks under the NAS-shaped uid:gid, before touching the NAS.

## Follow-up issues to file

- Derive `VERSION_NUMBER` from `pyproject.toml` at build time instead of the
  hardcoded Dockerfile `ENV` (drift risk; unmaintained since 1.3.0).
- Window B (CI runtime moves to rootless podman socket: buildah/classic
  build, staging caddy routing) — tracked on the docker-compose-templates
  side; not this PR.
- Registry accepts anonymous pull *and* push (verified from LAN) — audit
  whether push should require auth; separate infra concern.
