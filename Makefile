.PHONY: sync validate audit test lint check serve docker-build docker-smoke export

sync:
	uv sync --extra dev

validate:
	uv run --frozen researchctl validate

audit:
	uv run --frozen researchctl stats

test:
	uv run --extra dev --frozen pytest -q

lint:
	uv run --extra dev --frozen ruff check service tests migrations scripts

check: validate lint test

serve:
	uv run --frozen research-sidecar

docker-build:
	docker build -t aspa-research-sidecar -f docker/Dockerfile .

docker-smoke: docker-build
	docker run --rm aspa-research-sidecar python -m service.cli --data-dir /data validate

export:
	uv run --frozen researchctl export build/sources.jsonl
