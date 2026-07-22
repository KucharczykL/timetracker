{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs_26
    python3
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

    _timed "uv venv --clear" uv venv --clear
    . .venv/bin/activate
    _timed "uv sync" uv sync
  '';
}
