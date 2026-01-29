{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs
    python3
    uv
    ruff
  ];

  shellHook = ''
    uv venv --clear
    . .venv/bin/activate
    uv sync
  '';
}
