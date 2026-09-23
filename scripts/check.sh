#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
uv run --extra dev --frozen researchctl validate
uv run --extra dev --frozen ruff check service tests migrations scripts
uv run --extra dev --frozen pytest -q
