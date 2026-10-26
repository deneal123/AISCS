.PHONY: sync validate audit novelty-check test lint repository-check imports-check reproducibility-check quick-check check serve docker-build docker-smoke docker-config docker-context export smoke
sync:
	uv sync --frozen --extra dev
validate:
	uv run --frozen researchctl validate
audit:
	uv run --frozen researchctl stats
novelty-check:
	uv run --frozen researchctl novelty-check
test:
	uv run --frozen --extra dev pytest -q
lint:
	uv run --frozen --extra dev ruff check service tests migrations scripts
repository-check:
	uv run --frozen python scripts/check_repository.py
imports-check:
	uv run --frozen python scripts/check_imports.py
reproducibility-check:
	uv run --frozen python scripts/check_reproducibility.py --renormalize
quick-check:
	uv run --frozen --extra dev python scripts/check.py --skip-mcp
check:
	uv run --frozen --extra dev python scripts/check.py
smoke:
	uv run --frozen python scripts/smoke.py
serve:
	uv run --frozen research-sidecar
docker-config:
	docker compose -f docker/compose.yaml config --quiet
	docker compose -f docker/compose.knowledge.yaml --profile knowledge config --no-interpolate --no-env-resolution --quiet
docker-build:
	docker build -t aspa-research-sidecar -f docker/Dockerfile .
docker-context:
	uv run --frozen python scripts/check_docker_context.py
docker-smoke: docker-build
	uv run --frozen python scripts/docker_smoke.py
export:
	uv run --frozen researchctl export build/sources.jsonl
