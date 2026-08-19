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
	uv run mypy packages/vypq-contracts/src packages/vypq-core/src packages/vypq-events/src apps/gateway/src
