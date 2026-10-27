#!/bin/bash
# Shared read-only preflight. Raw Compose output may contain dotenv values,
# credentials or paths: never echo it, even when interpolation fails.

compose_preflight_error() {
    local diagnostic="${1:-}"
    local key
    # Only source-controlled deployment key names may cross this boundary.
    # Unknown parser messages fail closed with a generic bounded code.
    for key in GPTHUB_WORKSPACE_COORDINATION_SECRET MINIO__ACCESS_KEY MINIO__SECRET_KEY NEO4J_PASSWORD GENERATOR_TOKEN; do
        if [[ "$diagnostic" == *"required variable $key is missing a value"* ]]; then
            printf '[ERROR] Compose configuration validation failed; code=missing_required_variable variable=%s\n' "$key" >&2
            return 0
        fi
    done
    printf '[ERROR] Compose configuration validation failed; code=invalid_configuration\n' >&2
}

compose_config_preflight() {
    local diagnostic
    # Capture both streams. Even stdout from a failed parser is untrusted.
    if diagnostic=$("$@" config --quiet 2>&1); then
        return 0
    fi
    compose_preflight_error "$diagnostic"
    return 1
}

# Aspa keeps the upstream entrypoints; this chooses only the requested application profile.
environment_value() {
    local value
    value=$(awk -F= -v wanted="$1" '$1 == wanted { value=substr($0,index($0,"=")+1) } END { print value }' "$ENV_FILE")
    printf '%s' "${value:-$2}"
}

select_application_compose() {
    local configured
    configured=$(awk -F= '$1 == "SERVICE__APPLICATION_PROFILE" { value=substr($0,index($0,"=")+1) } END { print value }' "$ENV_FILE")
    SERVICE_APPLICATION_PROFILE="${APPLICATION_PROFILE:-${configured:-gpthub}}"
    if [ "$SERVICE_APPLICATION_PROFILE" = "simulation" ]; then
        if [ "$MODE" = "dev" ]; then
            COMPOSE_FILE="docker-compose.simulation.yaml"
        else
            COMPOSE_FILE="docker-compose.simulation.prod.yaml"
        fi
    fi
}

# Check prerequisites before changing a live production stack. Never print values.
production_simulation_preflight() {
    [ "$MODE" = "prod" ] && [ "${SERVICE_APPLICATION_PROFILE:-gpthub}" = "simulation" ] || return 0
    local key value
    for key in MINIO__ACCESS_KEY MINIO__SECRET_KEY; do
        value=$(awk -F= -v wanted="$key" '$1 == wanted { print substr($0,index($0,"=")+1) }' "$ENV_FILE")
        if [ -z "$value" ]; then
            printf '[ERROR] Production S3 credential is not configured; variable=%s\n' "$key" >&2
            return 1
        fi
    done
    if [ ! -s ../infra/nginx/certs/aiscs/certificate.pem ] || [ ! -s ../infra/nginx/certs/aiscs/private.pem ]; then
        printf '[ERROR] AISCS TLS certificate is not provisioned; code=aiscs_tls_missing\n' >&2
        return 1
    fi
}
