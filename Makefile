.PHONY: test test-all lint fmt typecheck
test:
	uv run pytest
test-all:
	uv run pytest -m ""
lint:
	uv run ruff check .
fmt:
	uv run ruff format .
typecheck:
	uv run mypy packages/vypq-core/src/vypq_core/host_registry.py
