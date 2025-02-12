{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs
    python3
    poetry
    ruff
  ];

  shellHook = ''
    python -m venv .venv
    . .venv/bin/activate
    poetry install
  '';
}
