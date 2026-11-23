#!/bin/bash
set -e

# ============================================================================
# Запуск стека AISCS
# ============================================================================
#
# Использование:
#   ./run.sh [--dev|--prod] [ДЕЙСТВИЕ]
#
# Действия:
#   (пусто)        поднять стек и дождаться готовности сервисов
#   --stop         остановить стек (контейнеры и сеть; данные сохраняются)
#   --restart      пересоздать сервисы
#   --status       показать состояние контейнеров и адреса
#   --logs [SVC]   поток логов всего стека или одного сервиса
#
# Конфигураций ровно две: docker-compose.dev.yaml и docker-compose.yaml.
# Обе поднимают генератор на видеокарте (target gpu-runtime, gpus: all).
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

cd "$(dirname "$0")" || exit 1
source ./compose_preflight.sh

MODE="dev"
ACTION="start"
LOGS_SERVICE=""

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_help() {
    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dev) MODE="dev"; shift ;;
        --prod) MODE="prod"; shift ;;
        --start) ACTION="start"; shift ;;
        --stop) ACTION="stop"; shift ;;
        --restart) ACTION="restart"; shift ;;
        --status) ACTION="status"; shift ;;
        --logs)
            ACTION="logs"; shift
            if [[ $# -gt 0 && "$1" != --* ]]; then LOGS_SERVICE="$1"; shift; fi
            ;;
        -h|--help) show_help ;;
        *)
            log_error "Неизвестная опция: $1"
            echo "Используйте --help для справки"
            exit 1
            ;;
    esac
done

if [ "$MODE" = "dev" ]; then
    COMPOSE_FILE="docker-compose.dev.yaml"
    PROJECT_NAME="aspa-dev"
else
    COMPOSE_FILE="docker-compose.yaml"
    PROJECT_NAME="aspa-prod"
fi
ENV_FILE=".env.${MODE}"

if [ ! -f "$COMPOSE_FILE" ]; then
    log_error "Файл $COMPOSE_FILE не найден!"
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    log_error "Файл $ENV_FILE не найден!"
    log_error "Docker Compose не сможет подставить переменные окружения."
    exit 1
fi

COMPOSE_CMD=(docker compose --env-file "$ENV_FILE" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" --profile "$MODE" --profile celery)

print_addresses() {
    local frontend_port backend_port minio_port console_port mailpit_port domain
    frontend_port=$(environment_value FRONTEND_PORT 8095)
    backend_port=$(environment_value BACKEND_PORT 8094)
    minio_port=$(environment_value MINIO_PORT 9000)
    if [ "$MODE" = "dev" ]; then
        log_info "Frontend:  http://localhost:${frontend_port}"
        log_info "Backend:   http://localhost:${backend_port}/api/health"
        log_info "MinIO:     http://localhost:${minio_port}"
        console_port=$(environment_value MINIO_CONSOLE_PORT 9001)
        mailpit_port=$(environment_value MAILPIT_PORT 8027)
        log_info "MinIO UI:  http://localhost:${console_port}"
        log_info "Mailpit:   http://localhost:${mailpit_port}"
    else
        domain=$(environment_value APP_DOMAIN localhost)
        log_info "Публичный адрес: https://${domain}"
    fi
    log_info "Генератор: http://generator:8090 (внутри сети, GPU)"
}

case "$ACTION" in
    start)
        log_info "Запуск стека: режим $MODE, файл $COMPOSE_FILE, проект $PROJECT_NAME"
        check_env_drift
        production_preflight
        if ! compose_config_preflight "${COMPOSE_CMD[@]}"; then
            log_error "Конфигурация невалидна; code=compose_config_invalid"
            exit 1
        fi
        log_info "Подъём сервисов..."
        # Код возврата Docker сохраняется: обёртка не имеет права превращать
        # осмысленный отказ (например, занятый порт) в безликое «1».
        up_status=0
        "${COMPOSE_CMD[@]}" up -d --remove-orphans || up_status=$?
        if [ "$up_status" -ne 0 ]; then
            log_error "Стек не поднялся; code=compose_up_failed"
            exit "$up_status"
        fi
        log_info "Ожидание готовности (до 180 с)..."
        if ! "${COMPOSE_CMD[@]}" up -d --wait --wait-timeout 180 >/dev/null 2>&1; then
            log_warning "Не все сервисы дошли до healthy за 180 с"
            "${COMPOSE_CMD[@]}" ps || true
        fi
        log_success "Стек запущен"
        print_addresses
        ;;
    stop)
        log_info "Остановка стека (проект $PROJECT_NAME)..."
        "${COMPOSE_CMD[@]}" down --remove-orphans
        log_success "Стек остановлен; данные томов сохранены"
        ;;
    restart)
        log_info "Пересоздание сервисов (проект $PROJECT_NAME)..."
        check_env_drift
        production_preflight
        "${COMPOSE_CMD[@]}" up -d --force-recreate --remove-orphans
        log_success "Сервисы пересозданы"
        print_addresses
        ;;
    status)
        "${COMPOSE_CMD[@]}" ps
        echo
        print_addresses
        ;;
    logs)
        if [ -n "$LOGS_SERVICE" ]; then
            "${COMPOSE_CMD[@]}" logs -f --tail 200 "$LOGS_SERVICE"
        else
            "${COMPOSE_CMD[@]}" logs -f --tail 100
        fi
        ;;
esac
