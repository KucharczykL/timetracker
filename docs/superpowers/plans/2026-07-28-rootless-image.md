# Rootless-Native Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Docker image run entirely as uid 1000 (no root anywhere), add `/health` + `/health/ready` probes, and switch CI to immutable image tags (issue #566).

**Architecture:** Delete the PUID/PGID root-remap machinery outright; `USER timetracker` baked into the image. Health endpoints are middleware (first in `MIDDLEWARE`) so probes bypass `CommonMiddleware`'s `ALLOWED_HOSTS` check. Version images minted only by a separate tag-triggered workflow that retags an existing `main-<sha>`.

**Tech Stack:** Django middleware, Dockerfile, supervisord, GitHub/Gitea Actions, `docker buildx imagetools`.

**Spec:** `docs/superpowers/specs/2026-07-28-rootless-image-design.md` — read it first; it carries rationale and verified claims (registry is anonymous, keep-id overrides `USER`, copy-up never fires for staging).

## Global Constraints

- All added text (comments, README, docs) terse: non-obvious intent only, no past narration, no issue refs (except forward TODOs).
- Verification gate is full `make check` (never a subset).
- Repo conventions: CLAUDE.md applies (complete-word identifiers, etc.).
- Registry: `registry.kucharczyk.xyz/timetracker`. Anonymous push/pull — no login steps.

---

### Task 1: Health middleware + tests

**Files:**
- Modify: `common/middleware.py` (add class), `timetracker/settings.py:94` (MIDDLEWARE head)
- Test: `tests/test_health.py` (new)

**Interfaces:**
- Produces: `common.middleware.HealthCheckMiddleware`; URLs `/health`, `/health/ready` (plain-text `ok` / 503 `unavailable`). Task 2's HEALTHCHECK and Task 7's quadlet probe depend on `/health`.

- [ ] **Step 1: Write failing tests** in `tests/test_health.py`:

```python
import pytest
from django.db import DatabaseError
from django.test import Client, override_settings


@override_settings(ALLOWED_HOSTS=["allowed.example"])
class TestHealthEndpoints:
    def test_health_bypasses_host_validation(self):
        response = Client().get("/health", SERVER_NAME="127.0.0.1")
        assert response.status_code == 200
        assert response.content == b"ok"

    def test_disallowed_host_still_rejected_elsewhere(self):
        response = Client().get("/", SERVER_NAME="127.0.0.1")
        assert response.status_code == 400

    def test_health_requires_no_auth(self):
        response = Client().get("/health", SERVER_NAME="allowed.example")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_ready_ok(self):
        response = Client().get("/health/ready", SERVER_NAME="127.0.0.1")
        assert response.status_code == 200

    def test_ready_db_failure_returns_503(self, monkeypatch):
        from common import middleware

        class BrokenConnection:
            def cursor(self):
                raise DatabaseError("down")

        monkeypatch.setattr(middleware, "connection", BrokenConnection())
        response = Client().get("/health/ready", SERVER_NAME="127.0.0.1")
        assert response.status_code == 503
```

Note: `Client(raise_request_exception=...)` not needed — `DisallowedHost` becomes a 400 via `CommonMiddleware` when `DEBUG=False`; if the test settings run with `DEBUG=True` and the 400 assertion misbehaves, add `@override_settings(DEBUG=False)` on the class.

- [ ] **Step 2: Run, verify fail:** `make test ARGS="tests/test_health.py -x"` — expect 404/400 failures (no middleware yet).

- [ ] **Step 3: Implement** in `common/middleware.py` (append; module docstring may need a small generalization since the module no longer holds only presentation prefs):

```python
from django.db import DatabaseError, connection
from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answer container health probes.

    Must sit first in MIDDLEWARE: probes hit 127.0.0.1, which
    CommonMiddleware's ALLOWED_HOSTS check would reject.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health":
            return HttpResponse("ok", content_type="text/plain")
        if request.path == "/health/ready":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except DatabaseError:
                return HttpResponse(
                    "unavailable", status=503, content_type="text/plain"
                )
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
```

`timetracker/settings.py`: insert `"common.middleware.HealthCheckMiddleware",` as the **first** entry of `MIDDLEWARE`.

- [ ] **Step 4: Run, verify pass:** `make test ARGS="tests/test_health.py"` then `make check-fast`.
- [ ] **Step 5: Commit** `feat: health endpoints as pre-host-validation middleware`.

---

### Task 2: Rootless image — Dockerfile, entrypoint, supervisor, config sweep

**Files:**
- Modify: `Dockerfile`, `entrypoint.sh`, `supervisor.conf`, `docker-compose.yml`, `.env.example`, `docs/configuration.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `/health` (Task 1) for HEALTHCHECK.
- Produces: image whose default user is `timetracker` (uid 1000); no PUID/PGID anywhere in this repo except staging workflow (Task 3).

- [ ] **Step 1: Dockerfile** — in the final stage:
  - apt list: drop `libcap2-bin`.
  - Replace the `mkdir -p /var/log/supervisor /etc/supervisor/conf.d /home/timetracker/data && chown …` tail of the apt RUN with: `mkdir -p /etc/supervisor/conf.d /home/timetracker/app/data && chown -R timetracker:timetracker /home/timetracker/app` (data dir at the real `DATA_DIR` default, owned before COPY; `--chown` COPYs keep it consistent).
  - After the `entrypoint.sh` COPY/chmod RUN, add:

```dockerfile
USER timetracker

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -sf http://127.0.0.1:8000/health || exit 1
```

  (`USER` before `ENTRYPOINT`; keep `EXPOSE 8000` / `ENV VERSION_NUMBER` as-is.)

- [ ] **Step 2: entrypoint.sh** — delete `PUID`/`PGID` assignments + comment lines, the `usermod`/`groupmod` block, both `chmod` lines, both `chown` lines, and `/var/log/supervisor` from the `mkdir`. Result keeps: shebang/`set -euo pipefail`, trimmed comment block (DATA_DIR/CREATE_DEFAULT_SUPERUSER/STAGING/LOAD_SAMPLE_DATA), `DATA_DIR` default, `mkdir -p "$DATA_DIR"`, migrate, collectstatic, the three conditional blocks verbatim, `exec supervisord`.
- [ ] **Step 3: supervisor.conf** — delete all four `user=` lines (`user=root` + three `user=timetracker`).
- [ ] **Step 4: Config sweep**
  - `docker-compose.yml`: delete the `PUID`/`PGID` environment lines.
  - `.env.example`: delete `PUID=1000` / `PGID=100` (and their comment if any).
  - `docs/configuration.md`: drop the `PUID`/`PGID` table row; add one sentence under the table: container runs as uid 1000 — mounted data dirs must be writable by that uid.
  - `CLAUDE.md` container-bootstrap bullet: remove `PUID`, `PGID` from the flag list.
- [ ] **Step 5: Verify:** `docker build -t timetracker:rootless-test .` (or `podman build`) succeeds; grep repo for `PUID` → only `.gitea/workflows/staging.yml` remains (Task 3).
- [ ] **Step 6: Commit** `feat: run container as uid 1000, drop PUID/PGID remap`.

---

### Task 3: Staging workflow — volume ownership + stale env

**Files:**
- Modify: `.gitea/workflows/staging.yml`

**Interfaces:**
- Consumes: image without root chown (Task 2) — this task is what keeps staging bootable.

- [ ] **Step 1:** In the seed step's `docker run … python:3.14-slim-bookworm sh -c "…"`, change the trailing `chown 1000:100 /dest/db.sqlite3` to `chown -R 1000:100 /dest` (uid 1000 must own the directory to create WAL/SHM sidecars; copy-up never fires because the volume is pre-seeded).
- [ ] **Step 2:** Delete `-e PUID=1000 \` and `-e PGID=100 \` from the deploy step.
- [ ] **Step 3:** Commit `fix: staging volume owned by uid 1000, drop remap env`.

---

### Task 4: Immutable CI tags + release workflows

**Files:**
- Modify: `.github/workflows/build-docker.yml`, `.gitea/workflows/build.yml`
- Create: `.github/workflows/release-image.yml`, `.gitea/workflows/release-image.yml`

**Interfaces:**
- Produces: registry tags `latest`, `main-<7-char-sha>` per main merge; `v<semver>` on release tag push. Task 7 pin option depends on `main-<sha>`.

- [ ] **Step 1:** In **both** build workflows' `build-and-push` job (files differ elsewhere — edit each in place, no copy-paste): delete the "Set Version" step; before the build step add:

```yaml
      - name: Compute short SHA
        run: echo "SHORT_SHA=${GITHUB_SHA::7}" >> $GITHUB_ENV
```

  and set tags to:

```yaml
          tags: |
            registry.kucharczyk.xyz/timetracker:latest
            registry.kucharczyk.xyz/timetracker:main-${{ env.SHORT_SHA }}
```

- [ ] **Step 2:** Create `.github/workflows/release-image.yml` (and an identical `.gitea/workflows/release-image.yml`):

```yaml
name: Release image

on:
  push:
    tags: ['v[0-9]+.[0-9]+.[0-9]+']

jobs:
  tag-image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      # Retag the commit's existing main-<sha> image; never rebuilds. Fails
      # if the main build hasn't pushed yet — rerun after it lands.
      - name: Retag as release
        run: |
          SHORT_SHA=$(git rev-parse --short=7 HEAD)
          docker buildx imagetools create \
            --tag "registry.kucharczyk.xyz/timetracker:${GITHUB_REF_NAME}" \
            "registry.kucharczyk.xyz/timetracker:main-${SHORT_SHA}"
```

  Gotchas encoded above: `tags:` filter lives ONLY in the new file (adding it to the existing `on: push` would stop branch CI entirely); sha comes from `git rev-parse` after checkout, not `GITHUB_SHA` (annotated-tag ambiguity).

- [ ] **Step 3:** Verify: `grep -c "VERSION_NUMBER" .github/workflows/build-docker.yml .gitea/workflows/build.yml` → 0 each. `actionlint` if available, else YAML-parse both new files.
- [ ] **Step 4:** Commit `feat: immutable main-<sha> tags; release images minted on vX.Y.Z tags`.

---

### Task 5: README run instructions

**Files:**
- Modify: `README.md` (append section)

- [ ] **Step 1:** Append (terse; adjust nothing above it):

````markdown
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
````

- [ ] **Step 2:** Commit `docs: image run instructions (docker + rootless podman)`.

---

### Task 6: Smoke test + gate + PR

**Files:** none (verification)

- [ ] **Step 1: Image path (docker default user):** build, then:

```bash
docker run -d --name tt-smoke -e SECRET_KEY=smoke -e APP_URL=http://localhost:8000 -p 18000:8000 timetracker:rootless-test
sleep 25
docker exec tt-smoke id -u          # expect 1000
curl -sf http://localhost:18000/health        # expect ok
curl -sf http://localhost:18000/health/ready  # expect ok
docker exec tt-smoke supervisorctl -c /etc/supervisor/conf.d/supervisor.conf status  # 3x RUNNING
docker inspect --format '{{.State.Health.Status}}' tt-smoke  # healthy (after start period)
docker rm -f tt-smoke
```

- [ ] **Step 2: keep-id-shaped path:** rerun with `--user 1000:100` (or `podman run --userns=keep-id:uid=1000,gid=100` if podman available) + a fresh host-dir volume owned `1000:100`; same checks. This simulates the NAS gid before touching it.
- [ ] **Step 3: Full gate:** `make check` — green, no subset.
- [ ] **Step 4:** Push branch, open PR against `main` referencing issue #566 (body: summary + spec/plan links; end with the standard generated-with footer). Merge per repo habit (`gh pr merge --merge`) after review.

---

### Task 7: Deployment rollout (post-merge; repo `~/git/docker-compose-templates`)

**Blocked on:** Task 6 PR merged AND CI having pushed the new `latest`.

- [ ] **Step 1:** Edit `quadlet/timetracker.container`: delete `User=0:0`, delete both `Environment=PUID…`/`Environment=PGID…` lines, keep `UserNS=keep-id:uid=%U,gid=%G`; replace `HealthCmd` with `curl -sf http://127.0.0.1:8000/health`; rewrite the header comment (terse, present-state: rootless-native image, runs as keep-id uid; pin option `main-<sha>`). Leave `secrets/dot-env` untouched (other containers read PUID/PGID).
- [ ] **Step 2:** Commit + push in that repo.
- [ ] **Step 3:** `ssh nas`: `cd ~/docker-compose-templates && git pull`, `systemctl --user daemon-reload`, `systemctl --user restart timetracker`. Verify: `podman exec timetracker id` → uid 1000; `podman healthcheck run timetracker` or `podman ps` → healthy; site answers (`curl -s -o /dev/null -w '%{http_code}' https://tracker.kucharczyk.xyz/login/` → 200).
- [ ] **Step 4:** Rollback path if red: restore the quadlet from git (`User=0:0` version) AND pin `Image=` to the pre-merge image (`…:1.7.0` — the last root-capable tag; new `latest` is non-root and would die under the restored quadlet's assumptions in reverse). Restart, verify, then debug forward.

---

### Task 8: Follow-up issues

- [ ] **Step 1:** `gh issue create` in `KucharczykL/timetracker`: derive `VERSION_NUMBER` from `pyproject.toml` at build time (hardcoded ENV drifts; untagged since 1.3.0).
- [ ] **Step 2:** Infra issue (docker-compose-templates repo, via tea or gh as appropriate): registry accepts anonymous **push** — decide whether to require auth.
- [ ] **Step 3:** Close issue #566 via PR merge (auto-close keyword in PR body) or manually with a rollout summary comment.
