#!/bin/sh
set -e

# Проверяем рантайм на старте: падать здесь лучше, чем 500 на первом запросе.
python3 -c "import duckdb, openpyxl; print('duckdb', duckdb.__version__, '| openpyxl', openpyxl.__version__)"

exec python3 /opt/duckdb-sidecar/service/app.py
