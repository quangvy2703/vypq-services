.PHONY: test test-all test-web test-web-e2e lint lint-web fmt typecheck
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
test-web:
	cd apps/dashboard && pnpm install --frozen-lockfile && pnpm test
lint-web:
	cd apps/dashboard && pnpm install --frozen-lockfile && pnpm lint
test-web-e2e:
	cd apps/dashboard && pnpm install --frozen-lockfile && pnpm exec playwright install --with-deps chromium && pnpm test:e2e
