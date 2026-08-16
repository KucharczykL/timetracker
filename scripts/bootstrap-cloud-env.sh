#!/usr/bin/env bash
#
# Bootstrap a Python 3.14 dev environment for timetracker in a cloud/CI box
# that has neither Nix nor a system Python 3.14.
#
# The repo pins `requires-python = ">=3.14"` and uses 3.14-only syntax
# (PEP 758 bare `except A, B:`), so anything older fails to even import.
#
# `uv python install 3.14` is the fast path, but the uv preinstalled on these
# boxes can be a year old, and uv's list of downloadable interpreters is baked
# into the binary: uv 0.8.x tops out at 3.14.0**rc2**. That rc satisfies a naive
# `>= 3.14` check while still being too old to run the project — pydantic calls
# `typing._eval_type(..., prefer_fwd_module=True)`, a kwarg added in 3.14 final,
# so `import ninja` dies before any test runs. So: upgrade uv from PyPI (which
# the agent proxy allows) when it doesn't know a final 3.14 yet, and reject
# pre-releases everywhere. conda-forge stays as a fallback for boxes where uv's
# interpreter download is blocked.
#
# After this runs, `.venv` is a 3.14 environment with all deps synced from the
# lockfile, and the Makefile's `uv run --frozen ...` targets (make check, make
# test, make lint, ...) use it directly. Every check target is --frozen, so
# none of them touch uv.lock.
#
# The database is part of that: every Django target routes through
# `ensure-postgres`, which builds an ignored loopback cluster (docs/database.md),
# so a box with no PostgreSQL 18 fails `make check` no matter how good its Python
# is. Step 5 provisions it here instead of leaving it to the first `make check`.
# It is the one non-fatal step — a box that cannot host a cluster (running as
# root, no matching build published) can still borrow one via DATABASE_URL, and
# the Python and JS toolchains above remain useful either way.
#
# Idempotent: re-running skips whatever already exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repo root: prefer git, fall back to the script's own dir (works whether the
# script lives at repo root or in a scripts/ subdir).
PROJECT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"
ENV_NAME="${ENV_NAME:-py314}"
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
# Where a PyPI-installed uv goes when the preinstalled one is too old to know
# about a released 3.14. Kept out of $HOME/.local/lib so it can't collide with
# anything the image put there.
UV_LIB_DIR="${UV_LIB_DIR:-$HOME/.local/share/uv-cli}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# uv is pre-installed but not always on PATH.
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { echo "error: uv not found on PATH" >&2; exit 1; }

# A 3.14 release candidate passes `>= (3,14)` but cannot run the project, so
# every interpreter check here demands a final release. One definition, used for
# the standalone interpreter and for the venv it ends up in.
IS_FINAL_314='import sys; sys.exit(0 if sys.version_info[:2] >= (3,14) and sys.version_info.releaselevel == "final" else 1)'

# ── 1. Make sure uv itself knows about a released 3.14 ───────────────────────
# uv ships its interpreter catalogue inside the binary, so an old uv can only
# offer 3.14.0rc2 no matter how many finals exist. `uv self update` needs the
# GitHub API (blocked here), but uv is also on PyPI, which is allowlisted.
uv_offers_final_314() {
  uv python list --all-versions 2>/dev/null | grep -qE '^cpython-3\.1[4-9]\.[0-9]+-'
}

if ! uv_offers_final_314; then
  log "uv ($(uv --version)) predates the 3.14 release; upgrading it from PyPI"
  if command -v python3 >/dev/null && python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install --quiet --upgrade --target "$UV_LIB_DIR" uv
    mkdir -p "$HOME/.local/bin"
    ln -sf "$UV_LIB_DIR/bin/uv" "$HOME/.local/bin/uv"
    hash -r
    log "uv is now $(uv --version)"
  else
    echo "warning: no pip to upgrade uv with; a 3.14 pre-release may be all it can offer" >&2
  fi
fi

# ── 2. Locate (or provision) a real CPython 3.14 interpreter ─────────────────
find_python314() {
  # Prefer anything already on the system; only fall back to provisioning one.
  for candidate in \
      "$CONDA_DIR/envs/$ENV_NAME/bin/python" \
      "$(command -v python3.14 || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ] \
       && "$candidate" -c "$IS_FINAL_314" 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

if ! PY314="$(find_python314)"; then
  log "Installing CPython $PYTHON_VERSION via uv"
  uv python install "$PYTHON_VERSION" || true
fi

if ! PY314="$(find_python314)"; then
  # uv couldn't reach python-build-standalone; conda-forge is a second source.
  if [ ! -x "$CONDA_DIR/bin/conda" ]; then
    log "Installing miniconda into $CONDA_DIR"
    curl -fsSL -o /tmp/miniconda.sh "$MINICONDA_URL"
    bash /tmp/miniconda.sh -b -p "$CONDA_DIR"
    rm -f /tmp/miniconda.sh
  fi
  log "Creating conda env '$ENV_NAME' with Python $PYTHON_VERSION (conda-forge only)"
  # --override-channels -c conda-forge avoids the defaults channels, whose
  # Terms-of-Service prompt hard-fails a non-interactive `conda create`.
  "$CONDA_DIR/bin/conda" create -y -n "$ENV_NAME" "python=$PYTHON_VERSION" \
    --override-channels -c conda-forge
  PY314="$(find_python314)"
fi
[ -n "${PY314:-}" ] || {
  echo "error: could not provision a final CPython $PYTHON_VERSION" >&2; exit 1;
}
log "Using interpreter: $PY314 ($("$PY314" --version))"

# ── 3. Build the project venv and sync deps from the lockfile ────────────────
cd "$PROJECT_DIR"
NEED_VENV=1
# A venv left behind by an earlier run of this script on an older uv can be a
# 3.14 pre-release, which is exactly what we must not keep.
if [ -x .venv/bin/python ] \
   && .venv/bin/python -c "$IS_FINAL_314" 2>/dev/null; then
  NEED_VENV=0
fi
if [ "$NEED_VENV" -eq 1 ]; then
  log "Creating .venv from $PY314"
  rm -rf .venv
  uv venv --python "$PY314" .venv
fi

log "Syncing dependencies (uv sync --frozen)"
uv sync --frozen   # --frozen: install exactly what uv.lock says, never rewrite it

# ── 4. JS toolchain (needed by make check's ts-check / test-ts steps) ────────
# Skip with SKIP_JS=1 for a Python-only workflow.
if [ "${SKIP_JS:-0}" != "1" ]; then
  # Both versions come from the files that already declare them, so bumping
  # either one doesn't leave this script behind. The fallbacks only matter if a
  # declaration is renamed away — better a stale pin than an unpinned install.
  NODE_VERSION="$(sed -n 's/^NODE_VERSION[[:space:]]*=[[:space:]]*//p' Makefile | head -1)"
  PNPM_VERSION="$(sed -n 's/.*"packageManager"[[:space:]]*:[[:space:]]*"pnpm@\([^"]*\)".*/\1/p' package.json | head -1)"
  [ -n "$NODE_VERSION" ] || { NODE_VERSION=26.4.0; echo "warning: no NODE_VERSION in Makefile; assuming $NODE_VERSION" >&2; }
  [ -n "$PNPM_VERSION" ] || { PNPM_VERSION=10.33.0; echo "warning: no packageManager in package.json; assuming pnpm@$PNPM_VERSION" >&2; }

  for node_bin in /opt/node26/bin /opt/node*/bin; do
    [ -d "$node_bin" ] && export PATH="$node_bin:$PATH" && break
  done
  if command -v npm >/dev/null; then
    # Node 26 no longer bundles Corepack, so install the pinned pnpm into the
    # user-owned bin directory already on PATH. The system node runs pnpm itself
    # perfectly well whatever its version — only the project's own JS needs 26.
    npm install --global --prefix "$HOME/.local" pnpm@"$PNPM_VERSION"
    if ! node -e "process.exit(Number(process.versions.node.split('.')[0]) >= Number('${NODE_VERSION%%.*}') ? 0 : 1)"; then
      # ts/date-time-presentation.ts uses Temporal, which arrives in Node 26; on
      # anything older the date/time formatters return null and ~11 vitest
      # assertions fail as if the code were broken. An older node on PATH is not
      # a dead end though — pnpm fetches the exact version on request, which is
      # what the Makefile does for the same reason. Mirror it rather than
      # skipping the JS deps and leaving `make check` unrunnable.
      log "PATH node is $(node --version); having pnpm fetch Node $NODE_VERSION"
      export npm_config_use_node_version="$NODE_VERSION"
    fi
    log "Installing JS deps (pnpm install --frozen-lockfile)"
    pnpm install --frozen-lockfile
  else
    echo "warning: no node/npm found; skipping JS deps (ts-check/test-ts will fail)" >&2
  fi
fi

# ── 5. PostgreSQL 18 dev cluster ─────────────────────────────────────────────
# `make ensure-postgres` reuses DATABASE_URL when one is already exported, and
# otherwise downloads the checksum-pinned PostgreSQL 18 build the harness pins
# (the distro package is normally too old). Skip the whole step with
# SKIP_POSTGRES=1.
POSTGRES_READY=1
if [ "${SKIP_POSTGRES:-0}" != "1" ]; then
  log "Provisioning the PostgreSQL 18 dev cluster (make ensure-postgres)"
  # Deliberately not fatal — see the header. Everything provisioned above stays
  # usable, and the closing message below stops promising a runnable `make check`.
  if ! make ensure-postgres; then
    POSTGRES_READY=0
    echo "warning: could not provision PostgreSQL 18. Every Django target (make check," >&2
    echo "         make test, make migrate) needs a database; export DATABASE_URL" >&2
    echo "         pointing at an existing PostgreSQL 18 server and re-run." >&2
  fi
fi

# ── 6. e2e browser ───────────────────────────────────────────────────────────
# e2e/conftest.py launches a browser it finds on PATH (google-chrome / chromium
# / chrome) via executable_path — the intended escape hatch from Nix/version
# issues. The image pre-installs Chromium under PLAYWRIGHT_BROWSERS_PATH but not
# on PATH, and its build often mismatches the locked playwright's expected
# revision (so the default resolver fails asking you to `playwright install`,
# which the image forbids). Symlinking the pre-installed binary onto PATH as
# `chromium` makes conftest launch it directly, revision mismatch notwithstanding.
if [ "${SKIP_E2E_BROWSER:-0}" != "1" ]; then
  have_browser=0
  for b in google-chrome-stable google-chrome chromium chrome; do
    command -v "$b" >/dev/null && { have_browser=1; break; }
  done
  if [ "$have_browser" -eq 0 ]; then
    chrome_bin="$(find "${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}" \
      -maxdepth 3 -type f -name chrome 2>/dev/null | head -1)"
    if [ -n "$chrome_bin" ]; then
      mkdir -p "$HOME/.local/bin"
      ln -sf "$chrome_bin" "$HOME/.local/bin/chromium"
      log "Linked e2e browser: $HOME/.local/bin/chromium -> $chrome_bin"
    else
      echo "warning: no chromium found under PLAYWRIGHT_BROWSERS_PATH; e2e will fail" >&2
    fi
  fi
fi

log "Done. Ensure PATH has \$HOME/.local/bin (uv + chromium) and node's bin, then:"
log "  uv run --frozen python --version   # 3.14.x"
if [ "$POSTGRES_READY" -eq 1 ]; then
  log "  make check                         # full gate: lint, mypy, ts, vitest, pytest+e2e"
else
  log "  export DATABASE_URL=...            # no local cluster; see docs/database.md"
  log "  make check                         # full gate (needs that database first)"
fi
