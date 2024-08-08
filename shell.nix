{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs
    (poetry.override { python3 = python312; })
  ];

  shellHook = ''
    poetry install
  '';
}
