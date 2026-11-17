{
  description = "Rust structure action development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";

  outputs = { nixpkgs, ... }:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      apps = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          checker = pkgs.writeShellApplication {
            name = "rust-structure";
            runtimeInputs = [ pkgs.python3 ];
            text = ''
              exec python3 ${./scripts}/check.py "$@"
            '';
          };
        in
        {
          default = {
            type = "app";
            program = "${checker}/bin/rust-structure";
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [ gnumake python3 ];
          };
        });
    };
}
