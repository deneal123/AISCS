#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
exec uv run --frozen --extra dev python scripts/check.py "$@"
