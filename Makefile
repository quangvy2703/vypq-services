.PHONY: test test-all lint fmt
test:
	uv run pytest
test-all:
	uv run pytest -m ""
lint:
	uv run ruff check .
fmt:
	uv run ruff format .
