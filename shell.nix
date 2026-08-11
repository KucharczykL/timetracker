{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs_26
    python3
    postgresql_18
    uv
    ruff
    pnpm_10
  ];

  # manylinux wheels with native extensions (greenlet, pulled in by
  # pytest-playwright) link against libstdc++.so.6, which the nixpkgs
  # Python cannot find on its default search path. Scoped to this dev
  # shell only — a global LD_LIBRARY_PATH would leak into other programs.
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ];

  shellHook = ''
    # Timing probe: shellHook only runs on a nix-direnv cache miss, so if you
    # see these lines during `direnv allow`/`cd`, the cache was rebuilt and
    # these are the slow steps. Set TIMETRACKER_SHELLHOOK_QUIET=1 to silence.
    _timed() {
      local _label="$1"; shift
      local _start=$(date +%s.%N)
      "$@"
      local _status=$?
      if [ -z "$TIMETRACKER_SHELLHOOK_QUIET" ]; then
        printf 'shellHook: %-16s %ss\n' "$_label" \
          "$(awk "BEGIN { printf \"%.2f\", $(date +%s.%N) - $_start }")" >&2
      fi
      return $_status
    }

    # Rebuild the venv only when it is missing or its interpreter no longer runs
    # — the case this guards is a nixpkgs bump garbage-collecting the store path
    # .venv/bin/python symlinks. Clearing unconditionally deleted a *working*
    # venv on every shell entry, so any `direnv exec .` / `nix-shell --run`
    # yanked the interpreter out from under a running `make dev`, which died as
    # `Unknown command: 'runserver'`. `uv sync` below reconciles a healthy venv
    # anyway, so the wipe bought nothing.
    if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "" 2>/dev/null; then
      _timed "uv venv --clear" uv venv --clear
    fi
    . .venv/bin/activate
    _timed "uv sync" uv sync
  '';
}
