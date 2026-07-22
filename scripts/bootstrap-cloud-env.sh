#!/usr/bin/env bash
#
# Bootstrap a Python 3.14 dev environment for timetracker in a cloud/CI box
# that has neither Nix nor a system Python 3.14.
#
# The repo pins `requires-python = ">=3.14"` and uses 3.14-only syntax
# (PEP 758 bare `except A, B:`), so anything older fails to even import.
# `uv python install 3.14` doesn't work here because uv pulls the interpreter
# from python-build-standalone on github.com, which the agent proxy blocks.
# conda-forge (via repo.anaconda.com) IS reachable, so we get 3.14 from there.
#
# After this runs, `.venv` is a 3.14 environment with all deps synced from the
# lockfile, and the Makefile's `uv run --frozen ...` targets (make check, make
# test, make lint, ...) use it directly. Every check target is --frozen, so
# none of them touch uv.lock.
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

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# uv is pre-installed but not always on PATH.
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { echo "error: uv not found on PATH" >&2; exit 1; }

# ── 1. Locate (or provision) a real CPython 3.14 interpreter ─────────────────
find_python314() {
  # Prefer anything already on the system; only fall back to conda.
  for candidate in \
      "$CONDA_DIR/envs/$ENV_NAME/bin/python" \
      "$(command -v python3.14 || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ] \
       && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,14) else 1)' 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

if ! PY314="$(find_python314)"; then
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
log "Using interpreter: $PY314 ($("$PY314" --version))"

# ── 2. Build the project venv and sync deps from the lockfile ────────────────
cd "$PROJECT_DIR"
NEED_VENV=1
if [ -x .venv/bin/python ] \
   && .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,14) else 1)' 2>/dev/null; then
  NEED_VENV=0
fi
if [ "$NEED_VENV" -eq 1 ]; then
  log "Creating .venv from $PY314"
  uv venv --python "$PY314" .venv
fi

log "Syncing dependencies (uv sync --frozen)"
uv sync --frozen   # --frozen: install exactly what uv.lock says, never rewrite it

# ── 3. JS toolchain (needed by make check's ts-check / test-ts steps) ────────
# Skip with SKIP_JS=1 for a Python-only workflow.
if [ "${SKIP_JS:-0}" != "1" ]; then
  # Node 26 is required for native Temporal. pnpm is pinned in package.json's
  # packageManager field; Node 26 no longer bundles Corepack, so provision the
  # exact pinned version into the user-owned bin directory already on PATH.
  for node_bin in /opt/node26/bin /opt/node*/bin; do
    [ -d "$node_bin" ] && export PATH="$node_bin:$PATH" && break
  done
  if command -v node >/dev/null \
     && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 26 ? 0 : 1)'; then
    npm install --global --prefix "$HOME/.local" pnpm@10.33.0
    log "Installing JS deps (pnpm install --frozen-lockfile)"
    pnpm install --frozen-lockfile
  else
    echo "warning: Node 26 and pnpm 10.33.0 are required; skipping JS deps (ts-check/test-ts will fail)" >&2
  fi
fi

# ── 4. e2e browser ───────────────────────────────────────────────────────────
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
log "  make check                         # full gate: lint, mypy, ts, vitest, pytest+e2e"
