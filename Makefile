.PHONY: sync validate build progress test lint repository-check quick-check check mcp-smoke
sync:
	uv sync --frozen --extra dev
validate:
	uv run --frozen presentationctl validate
build:
	uv run --frozen presentationctl build PRES-001 --profile draft
	uv run --frozen presentationctl build PRES-002 --profile draft
progress:
	uv run --frozen presentationctl progress-snapshot --apply
test:
	uv run --frozen --extra dev pytest -q
lint:
	uv run --frozen --extra dev ruff check service tests scripts
repository-check:
	uv run --frozen python scripts/check_repository.py
quick-check:
	uv run --frozen --extra dev python scripts/check.py --skip-build --skip-mcp
check:
	uv run --frozen --extra dev python scripts/check.py
mcp-smoke:
	uv run --frozen python scripts/mcp-smoke.py
