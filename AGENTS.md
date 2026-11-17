# Rust Structure Action

A small, dependency-free Python implementation of reusable Rust source and
module-folder guardrails, distributed as a GitHub composite action and a Nix
CLI. Keep the action, local CLI, and tests backed by the same checker code.

## Checker behavior

- Preserve the Rust-aware counting that excludes comments, literals, and
  `#[cfg(test)]` code from production line totals.
- Keep repository-specific paths, limits, and exception files configurable;
  do not hardcode a consuming repository's layout.
- Existing over-limit source files may remain unchanged or shrink, but new or
  growing violations fail. Exception ceilings may only decrease.
- Keep parsing standard-library-only so the composite action has no install
  step or third-party Python dependencies.

## Commands and verification

- `nix develop -c make check`: checker smoke test, unit tests, and Python compile.
- `make structure`: run the checker against this repository.
- `make test`: run the checker unit tests.
- Test the action CLI and JSON configuration when changing the checker or its
  inputs. Keep the examples synthetic and free of real repository data.

## Contributions

- Keep changes focused and use Conventional Commits.
- Create a PR for completed work and follow
  `.github/PULL_REQUEST_TEMPLATE.md`.
- Tag released action versions only after CI passes. Keep the major tag (such as
  `v1`) pointing at the latest compatible release.
