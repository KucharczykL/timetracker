{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs
    python3
    uv
    ruff
    pnpm
  ];

  # manylinux wheels with native extensions (greenlet, pulled in by
  # pytest-playwright) link against libstdc++.so.6, which the nixpkgs
  # Python cannot find on its default search path. Scoped to this dev
  # shell only — a global LD_LIBRARY_PATH would leak into other programs.
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ];

  shellHook = ''
    uv venv --clear
    . .venv/bin/activate
    uv sync
  '';
}
