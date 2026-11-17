# rust-structure

A reusable GitHub Action and local CLI for enforcing Rust source, test, and
module-folder size guardrails across repositories.

## GitHub Action

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0
- uses: caelurium/rust-structure@v1
  with:
    base-ref: ${{ github.event.pull_request.base.sha || 'HEAD^' }}
    config: .github/rust-structure.json
```

The checkout needs the base revision for legacy-file and exception ratcheting.
The optional JSON config selects source paths, limits, and an exceptions file.
Without a config, the action scans the repository with the default limits.

Example config:

```json
{
  "paths": ["src", "crates"],
  "limits": {
    "source": 800,
    "source_hard": 1500,
    "tests": 1000,
    "folder_soft": 40,
    "folder_hard": 60
  },
  "exceptions_file": "scripts/structure/exceptions.txt"
}
```

## Local use

The same checker is exposed as a Nix app and as a Python script:

```sh
nix run . -- --root . --base HEAD --config .github/rust-structure.json
python3 scripts/check.py --root . --base HEAD --config .github/rust-structure.json
```

## Consumers

Initial consumers are [Caelum](https://github.com/caelurium/caelum) and
[boat-sdk-rs](https://github.com/caelurium/boat-sdk-rs).
