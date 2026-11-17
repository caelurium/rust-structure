#!/usr/bin/env python3
"""Rust size and capability-folder guardrails for local and GitHub Action use."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from rust import is_test, measure

DEFAULT_LIMITS = {
    "source": 800,
    "source_hard": 1500,
    "tests": 1000,
    "folder_soft": 40,
    "folder_hard": 60,
}
EXCEPTION_KINDS = {"source", "tests", "folder", "family"}


def load_config(root, config_path):
    config = {"paths": ["."], "limits": DEFAULT_LIMITS.copy(), "exceptions_file": None}
    if config_path:
        path = Path(config_path)
        if not path.is_absolute():
            path = root / path
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("config must be a JSON object")
        unknown = set(data) - {"paths", "limits", "exceptions_file"}
        if unknown:
            raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))}")
        config["paths"] = data.get("paths", config["paths"])
        config["limits"].update(data.get("limits", {}))
        config["exceptions_file"] = data.get("exceptions_file")
    if not isinstance(config["paths"], list) or not config["paths"] or not all(
        isinstance(path, str) and path for path in config["paths"]
    ):
        raise ValueError("config paths must be a non-empty list of path strings")
    if not isinstance(config["limits"], dict) or set(config["limits"]) != set(DEFAULT_LIMITS):
        raise ValueError(f"config limits must contain exactly: {', '.join(DEFAULT_LIMITS)}")
    if not all(isinstance(value, int) and value > 0 for value in config["limits"].values()):
        raise ValueError("all config limits must be positive integers")
    if config["limits"]["source_hard"] < config["limits"]["source"]:
        raise ValueError("source_hard must be at least source")
    if config["limits"]["folder_hard"] < config["limits"]["folder_soft"]:
        raise ValueError("folder_hard must be at least folder_soft")
    if config["exceptions_file"] is not None and not isinstance(config["exceptions_file"], str):
        raise ValueError("exceptions_file must be a path string")
    return config


def parse_exceptions(text):
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"invalid exception: {line}")
        kind, path, ceiling = fields
        key = (kind, path)
        if kind not in EXCEPTION_KINDS or key in result:
            raise ValueError(f"invalid or duplicate exception: {line}")
        result[key] = int(ceiling)
        if result[key] <= 0:
            raise ValueError(f"invalid ceiling: {line}")
    return result


def ratchet(previous, current):
    return [
        f"exception may not be added or raised: {kind} {path} ({value})"
        for (kind, path), value in current.items()
        if (kind, path) not in previous or value > previous[(kind, path)]
    ]


def hard_limit(kind, limits):
    return {
        "source": limits["source_hard"],
        "tests": limits["tests"],
        "folder": limits["folder_hard"],
        "family": 0,
    }[kind]


def exception_threshold(kind, limits):
    return {
        "source": limits["source"],
        "tests": limits["tests"],
        "folder": limits["folder_hard"],
        "family": 0,
    }[kind]


def folder_sizes(paths, limits=DEFAULT_LIMITS):
    folders = defaultdict(list)
    subdirs = defaultdict(set)
    for path in map(PurePosixPath, paths):
        for parent in path.parents:
            if parent.parent != parent:
                subdirs[str(parent.parent)].add(parent.name)
        if is_test(str(path)) or path.parent.name in {"examples", "benches", "bin"}:
            continue
        folders[str(path.parent)].append(path.stem)
    result = {}
    for folder, stems in folders.items():
        if len(stems) > limits["folder_soft"]:
            result[("folder", folder)] = len(stems)
        families = Counter(
            re.split(r"[_-]", stem, maxsplit=1)[0]
            for stem in stems if "_" in stem or "-" in stem
        )
        for name, count in families.items():
            has_base = name in stems or name in subdirs[folder]
            if count >= (2 if has_base else 3):
                result[("family", f"{folder}/{name}_*")] = count
    return result


def rust_paths(root, include_paths):
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    if include_paths:
        command.extend(["--", *include_paths])
    output = subprocess.check_output(command, cwd=root).decode().split("\0")
    return sorted({path for path in output if path.endswith(".rs") and (root / path).is_file()})


def inventory(root, paths, limits):
    result = folder_sizes(paths, limits)
    for path in paths:
        size = measure(path, (root / path).read_text())
        if size.source > limits["source"]:
            result[("source", path)] = size.source
        if size.tests > limits["tests"]:
            result[("tests", path)] = size.tests
    return result


def diagnostics(sizes, exceptions, baseline_sizes=None, changed_paths=None, limits=DEFAULT_LIMITS):
    baseline_sizes = baseline_sizes or {}
    changed_paths = changed_paths or set()
    rows = []
    for (kind, path), count in sorted(sizes.items()):
        limit = exceptions.get((kind, path), hard_limit(kind, limits))
        level = "warning"
        if kind == "source" and count > limits["source"] and (kind, path) not in exceptions:
            baseline = baseline_sizes.get(path)
            legacy_not_growing = baseline is not None and baseline > limits["source"] and count <= baseline
            if count > limits["source_hard"] or not legacy_not_growing or (
                path in changed_paths and count == baseline
            ):
                level = "error"
        elif count > limit:
            level = "error"
        detail = {
            "source": "non-test lines",
            "tests": "test lines",
            "folder": "source files",
            "family": "prefixed sibling modules",
        }[kind]
        hint = "group this capability into a folder" if kind in {"folder", "family"} else "extract a focused module"
        if kind == "source" and count > limits["source"] and level == "warning":
            message = f"{count} {detail}; existing over-limit file must shrink when changed: {hint}"
        else:
            message = f"{count} {detail}; blocking limit {limit}: {hint}"
        rows.append((level, path, message))
    return rows


def git_output(root, args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"cannot run git {' '.join(args)}")
    return result.stdout


def baseline_source_sizes(root, base, sizes):
    result = {}
    for (kind, path), _ in sizes.items():
        if kind != "source":
            continue
        previous = subprocess.run(
            ["git", "show", f"{base}:{path}"], cwd=root, capture_output=True, text=True
        )
        if previous.returncode == 0:
            result[path] = measure(path, previous.stdout).source
    return result


def tighten(exceptions, sizes, limits):
    return {
        key: min(ceiling, sizes[key])
        for key, ceiling in exceptions.items()
        if sizes.get(key, 0) > exception_threshold(key[0], limits)
    }


def read_exceptions(root, base, exceptions_file):
    if not exceptions_file:
        return {}, {}, None
    path = root / exceptions_file
    current = parse_exceptions(path.read_text())
    previous = subprocess.run(
        ["git", "show", f"{base}:{exceptions_file}"], cwd=root, capture_output=True, text=True
    )
    baseline = parse_exceptions(previous.stdout) if previous.returncode == 0 else {}
    return current, baseline, exceptions_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="checked-out repository root")
    parser.add_argument("--base", default="HEAD", help="baseline revision for ratcheting checks")
    parser.add_argument("--config", help="optional JSON config path relative to the repository root")
    parser.add_argument("--update-exceptions", action="store_true", help="lower or remove resolved exceptions")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        config = load_config(root, args.config)
        paths = rust_paths(root, config["paths"])
        sizes = inventory(root, paths, config["limits"])
        base = git_output(root, ["rev-parse", "--verify", f"{args.base}^{{commit}}"]).strip()
        changed = set(git_output(root, ["diff", "--name-only", base, "--"]).splitlines())
        baseline = baseline_source_sizes(root, base, sizes)
        exceptions, previous_exceptions, exceptions_file = read_exceptions(
            root, base, config["exceptions_file"]
        )
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR {error}")
        return 1

    errors = ratchet(previous_exceptions, exceptions)
    if args.update_exceptions and not errors and exceptions_file:
        exceptions = tighten(exceptions, sizes, config["limits"])
        lines = ["# kind path ceiling; existing violations only, ceilings may only decrease."]
        lines.extend(f"{kind} {path} {ceiling}" for (kind, path), ceiling in sorted(exceptions.items()))
        (root / exceptions_file).write_text("\n".join(lines) + "\n")
    for key, ceiling in exceptions.items():
        if sizes.get(key, 0) < ceiling:
            errors.append(f"lower or remove resolved exception: {' '.join(key)}; run --update-exceptions")
    for error in errors:
        print(f"ERROR {error}")

    rows = diagnostics(sizes, exceptions, baseline, changed, config["limits"])
    for level, path, message in rows:
        print(f"{level.upper():7} {path}: {message}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::{level} file={path}::{message}")
    failures = len(errors) + sum(level == "error" for level, _, _ in rows)
    print(f"Structure: {len(paths)} Rust files, {failures} errors, {len(rows) - failures + len(errors)} warnings")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
