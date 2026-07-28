# Rootless-native Docker image (issue #566)

Date: 2026-07-28
Issue: https://github.com/KucharczykL/timetracker/issues/566

## Goal

The NAS deployment moved to a rootless Podman quadlet. The image currently
*requires* starting as root (`User=0:0` + `UserNS=keep-id`) purely because
`entrypoint.sh` unconditionally runs `usermod`/`groupmod`/`chown` under
`set -e`. Make the image rootless-native: no root anywhere, meaningful health
probe, immutable image tags, and documented run instructions.

Decision: **full non-root**, not a dual-path guard. The PUID/PGID remap
machinery is deleted outright. Foreclosed: root-docker deployments with host
data owned by uid≠1000 lose the in-container remap escape hatch (they must
chown the host dir or use `--user`/keep-id). Both real consumers (NAS quadlet,
staging) are uid 1000; the remap served only the pattern being left.

## 1. Dockerfile + entrypoint + supervisor

- **Dockerfile**: add `USER timetracker` before `ENTRYPOINT`. Pre-create
  `/home/timetracker/app/data` owned `timetracker:timetracker` so docker
  named-volume copy-up inherits ownership (staging relies on named volumes).
  Drop `libcap2-bin` if nothing calls `setcap` (both ports >1024 — verify
  during implementation). Add `HEALTHCHECK` probing `/health` (see §2).
- **entrypoint.sh**: delete `PUID`/`PGID` vars, `usermod`/`groupmod`, every
  `chown`/`chmod` line. Keep `mkdir -p "$DATA_DIR"`, migrate, collectstatic,
  the `STAGING`/`LOAD_SAMPLE_DATA`/`CREATE_DEFAULT_SUPERUSER` blocks, and
  `exec supervisord`. Everything runs as uid 1000 start to finish, including
  migrate/collectstatic (today they run as root).
- **supervisor.conf**: remove every `user=` key (including
  `[supervisord] user=root`). One conf, no per-program user switching —
  supervisord and all programs already share one uid.

## 2. Health endpoints

- New middleware, **first** in `MIDDLEWARE`: `/health` → 200 `ok` (liveness,
  no DB); `/health/ready` → `SELECT 1` → 200, else 503 (readiness).
  Middleware rather than URLconf because `ALLOWED_HOSTS` rejection happens
  before routing — the probe must work with
  `curl -f http://127.0.0.1:8000/health`, no `Host:` header hack, no auth.
- Dockerfile `HEALTHCHECK` uses `/health` (liveness). Restarting the
  container never fixes a busy SQLite, so the restart-triggering probe stays
  DB-free; `/health/ready` exists for runtimes that want the deeper check.
- Caddy's catch-all `reverse_proxy` already forwards both paths.
- Tests: bogus `Host:` header still 200; unauthenticated 200 (no login
  redirect); `/health/ready` 503 when the DB connection fails (mocked);
  normal requests unaffected by the middleware.

## 3. Immutable image tags

Applies to **both** `.github/workflows/build-docker.yml` and
`.gitea/workflows/build.yml` (they push identical tags today):

- Per main merge: push `latest` + immutable `main-<short-sha>` (rollback/pin
  target). Delete the `VERSION_NUMBER` tag push and the "Set Version" step.
- New tag-triggered job, semver tags only (`on: push: tags:
  ['v[0-9]+.[0-9]+.[0-9]+']` — releases switch to `vX.Y.Z` naming from here
  on; historical bare tags `1.1.0`–`1.3.0` stay as-is and never trigger it):
  retag the already-built
  `main-<short-sha>` of the tagged commit as `timetracker:<tag>` (verbatim,
  e.g. `timetracker:v1.8.0` — no prefix-stripping logic) via
  `docker buildx imagetools create` (or equivalent) — no rebuild, version tag
  minted exactly once → immutable. If the tag is pushed before the main-merge
  build finished, the retag fails; rerun the job (acceptable — releases are
  cut from already-built main commits).
- Release process (manual, when ready): bump version in `pyproject.toml` +
  Dockerfile `ENV VERSION_NUMBER`, merge, `git tag vX.Y.Z && git push origin
  vX.Y.Z`, `gh release create vX.Y.Z --generate-notes` (GitHub) / `tea
  release create --tag vX.Y.Z` (Gitea).

## 4. README

New "Running the image" section:

- `docker run` example: data volume mount, `SECRET_KEY`, port 8000. Note the
  container runs as uid 1000 — the host data dir must be writable by it.
- Rootless Podman: quadlet snippet with `UserNS=keep-id:uid=1000` (no
  `User=` needed — image default user is non-root).
- Health endpoints (`/health`, `/health/ready`) and tag scheme (`latest`
  moves, `main-<sha>` immutable, `vX.Y.Z` minted on release tags).

## 5. Deployment rollout (post-merge, other repo)

In `~/git/docker-compose-templates` after the image PR merges and CI pushes:

- Quadlet `quadlet/timetracker.container`: drop `User=0:0`, keep
  `UserNS=keep-id`, drop `PUID`/`PGID` env, `HealthCmd` →
  `curl -sf http://127.0.0.1:8000/health` (Host-header hack gone), update
  header comment (root-then-drop description obsolete), note the
  `main-<sha>` pin option.
- `ssh nas`: pull, `systemctl --user daemon-reload && systemctl --user
  restart timetracker`; verify process uid is 1000 (host-side `lukas`),
  health status `healthy`, site reachable.

## 6. Verification

- Full `make check` (the repo gate) before PR.
- Local image smoke test: build, `docker/podman run` with **no** user flags,
  confirm entrypoint completes (migrate + collectstatic), supervisord starts
  all three programs, `/health` returns 200, `/health/ready` returns 200,
  and `id -u` inside the container is 1000.

## Follow-up issues to file

- Derive `VERSION_NUMBER` from `pyproject.toml` at build time instead of the
  hardcoded Dockerfile `ENV` (drift risk).
- Window B (CI runtime moves to rootless podman socket: buildah/classic
  build, staging caddy routing) — tracked on the docker-compose-templates
  side; not this PR.
