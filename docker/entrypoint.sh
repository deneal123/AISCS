#!/bin/sh
set -e

# Оба рантайма проверяем на старте: java нужна opendataloader, soffice — office-форматам.
# Падать здесь лучше, чем отдавать 500 на первом же документе.
java -version 2>&1 | head -1
soffice --version 2>/dev/null | head -1 || echo "WARN: soffice unavailable — office formats will fail"

exec python3 /opt/odl-sidecar/service/app.py
