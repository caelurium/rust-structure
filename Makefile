.DEFAULT_GOAL := help

.PHONY: help structure test lint check

help:
	@printf '%s\n' \
	  'Rust structure action development:' \
	  '  make structure  Run the checker on this repository' \
	  '  make test       Run checker tests' \
	  '  make lint       Compile Python sources' \
	  '  make check      Run all checks'

structure:
	python3 scripts/check.py --root . --base HEAD --config .github/rust-structure.json

test:
	python3 -m unittest discover -s scripts -p 'test_*.py'

lint:
	python3 -m compileall -q scripts

check: structure test lint
