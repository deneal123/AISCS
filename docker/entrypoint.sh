#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

python -m service.cli --data-dir "${RESEARCH_DATA_DIR}" validate >/tmp/research-validation.json
exec python -m service.app
