#!/bin/bash
set -e

# ============================================================================
# Сборка образов AISCS
# ============================================================================
#
# Использование:
#   ./build.sh [OPTIONS]
#
# Опции:
#   --dev          Сборка для разработки (по умолчанию)
#   --prod         Сборка для продакшна
#   --no-cache     Сборка без кэша Docker
#   -h, --help     Показать это сообщение
#
# Конфигураций ровно две: docker-compose.dev.yaml и docker-compose.yaml.
# Обе собирают генератор с GPU (target gpu-runtime).
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

cd "$(dirname "$0")" || exit 1
source ./compose_preflight.sh

MODE="dev"
NO_CACHE=""

show_help() {
    head -22 "$0" | tail -18 | sed 's/^# //' | sed 's/^#//'
    exit 0
}

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --dev) MODE="dev"; shift ;;
        --prod) MODE="prod"; shift ;;
        --no-cache) NO_CACHE="--no-cache"; shift ;;
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

log_info "============================================"
log_info "Build"
log_info "============================================"
log_info "Режим: $MODE"
log_info "Compose файл: $COMPOSE_FILE"
log_info "Compose project: $PROJECT_NAME"
[ -n "$NO_CACHE" ] && log_info "Кэш: отключен"
log_info "============================================"

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

if ! compose_config_preflight "${COMPOSE_CMD[@]}"; then
    exit 1
fi

log_info "Сборка образов..."
build_status=0
"${COMPOSE_CMD[@]}" build $NO_CACHE || build_status=$?
if [ "$build_status" -ne 0 ]; then
    log_error "Сборка не удалась; code=compose_build_failed"
    exit "$build_status"
fi

log_success "Образы собраны"
