.PHONY: install test run

install:
	pip install -e ".[dev]"

test:
	pytest -q

run:
	cas-scanner
