.PHONY: sync validate build test lint check
sync:
	uv sync --extra dev
validate:
	uv run --frozen pubctl validate
build:
	uv run --frozen pubctl build PUB-TEMPLATE-001 --profile draft
test:
	uv run --extra dev --frozen pytest -q
lint:
	uv run --extra dev --frozen ruff check service tests scripts/mcp-smoke.py
check: validate lint test build
