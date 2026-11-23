#!/bin/bash
# Общие проверки конфигурации для build.sh и run.sh.
#
# Здесь нет выбора «прикладного» compose-файла: конфигураций ровно две,
# docker-compose.dev.yaml и docker-compose.yaml, и режим задаёт одну из них.

# Ключи, отсутствие которых надо назвать пользователю по имени. Всё остальное
# сообщается обезличенно: подставлять в диагностику произвольную строку из
# вывода Compose нельзя, там бывают значения секретов.
compose_preflight_error() {
    local message="$1"
    local known key

    for key in MINIO__ACCESS_KEY MINIO__SECRET_KEY PG__PASSWORD REDIS__PASSWORD GENERATOR_TOKEN AUTH__SECRET; do
        if printf '%s\n' "$message" | grep -q "$key"; then
            echo "[ERROR] Не задана обязательная переменная: $key"
            echo "[ERROR] code=missing_required_variable variable=$key"
            return 0
        fi
    done

    echo "[ERROR] Конфигурация Compose невалидна (значения не печатаются)."
    echo "[ERROR] code=invalid_configuration"
}

# Тихая проверка: вывод Compose не печатается, потому что в нём бывают секреты.
compose_config_preflight() {
    local message
    if message=$("$@" config --quiet 2>&1); then
        return 0
    fi
    compose_preflight_error "$message"
    return 1
}

# Значение ключа из env-файла с дефолтом.
environment_value() {
    local key="$1"
    local default="$2"
    local value=""

    if [ -f "$ENV_FILE" ]; then
        value=$(awk -v key="$key" '
            index($0, key "=") == 1 { value=substr($0, length(key)+2) }
            END { print value }
        ' "$ENV_FILE")
        value=$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//')
    fi

    if [ -z "$value" ]; then
        printf '%s' "$default"
    else
        printf '%s' "$value"
    fi
}

# Прод не поднимается без TLS-сертификата и учётных данных объектного хранилища:
# молчаливая работа с дефолтным minioadmin на проде — это открытое хранилище.
production_preflight() {
    [ "$MODE" = "prod" ] || return 0

    local access_key secret_key
    access_key=$(environment_value MINIO__ACCESS_KEY "")
    secret_key=$(environment_value MINIO__SECRET_KEY "")
    if [ -z "$access_key" ] || [ -z "$secret_key" ]; then
        echo "[ERROR] Для прода нужны MINIO__ACCESS_KEY и MINIO__SECRET_KEY."
        echo "[ERROR] code=missing_required_variable variable=MINIO__SECRET_KEY"
        return 1
    fi

    # Каталог монтируется в nginx как /etc/nginx/certs, а шаблон ждёт
    # certificate.pem и private.pem прямо в нём.
    if [ ! -f ../infra/nginx/certs/certificate.pem ] || [ ! -f ../infra/nginx/certs/private.pem ]; then
        echo "[ERROR] Нет сертификата TLS для домена AISCS в ../infra/nginx/certs/."
        echo "[ERROR] code=aiscs_tls_missing"
        return 1
    fi
}

# Ключи, объявленные в шаблоне, но отсутствующие в рабочем env-файле. Это
# предупреждение, а не отказ: значение может приходить из compose-дефолта.
# Значения не печатаются ни при каких условиях.
check_env_drift() {
    local example="./${ENV_EXAMPLE:-.env.example}"
    [ -f "$example" ] && [ -f "$ENV_FILE" ] || return 0

    local missing
missing=$(comm -23 \
        <(grep -E '^[A-Z_][A-Z0-9_]*=' "$example" | cut -d= -f1 | LC_ALL=C sort -u) \
        <(grep -E '^[A-Z_][A-Z0-9_]*=' "$ENV_FILE" | cut -d= -f1 | LC_ALL=C sort -u))

    if [ -n "$missing" ]; then
        echo "[WARN] В $ENV_FILE нет ключей из шаблона (берутся дефолты кода или compose):"
        printf '%s\n' "$missing" | sed -e 's/^/  - /'
        echo "[WARN] code=env_drift"
    fi
}
