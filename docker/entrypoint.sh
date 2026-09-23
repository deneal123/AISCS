#!/bin/sh
set -eu

python -m service.cli --data-dir "${RESEARCH_DATA_DIR}" validate >/tmp/research-validation.json
exec python -m service.app
