#!/bin/bash
set -e

# ============================================================================
# Run Script
# ============================================================================
#
# Использование:
#   ./run.sh [OPTIONS]
#
# Опции:
#   --dev          Запуск в режиме разработки (по умолчанию)
#   --prod         Запуск в продакшн режиме
#   --stop         Остановить все сервисы
#   --restart      Перезапустить все сервисы
#   --logs [NAME]  Показать логи (опционально: имя контейнера)
#   --status       Показать статус сервисов
#   -h, --help     Показать это сообщение
#
# Примеры:
#   ./run.sh                    # Запуск dev окружения
#   ./run.sh --prod             # Запуск prod окружения
#   ./run.sh --stop             # Остановка всех сервисов
#   ./run.sh --logs             # Просмотр логов всех сервисов
#   ./run.sh --logs backend     # Просмотр логов backend
#   ./run.sh --status           # Статус контейнеров
#
# Архитектура:
#   Основной стек (docker-compose*.yaml):
#     - frontend    : React приложение (порт 3000)
#     - backend     : FastAPI сервер (порт 8000)
#     - postgres    : База данных PostgreSQL
#     - redis       : Кэш и результаты Celery
#     - celery      : Воркер для фоновых задач
#     - minio       : S3-совместимое хранилище (порт 9000, UI: 9001)
#     - nginx       : Reverse proxy (порт 80)
#
# ============================================================================

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Переходим в директорию скрипта
cd "$(dirname "$0")" || exit 1
source ./compose_preflight.sh
source ./local_llm_bootstrap.sh

# Параметры по умолчанию
MODE="dev"
MODE_EXPLICIT=false
ACTION="start"
LOG_SERVICE=""
# ⚠️ ОТСЮДА УДАЛЁН ФЛАГ --release И ВЕТКА start-release. Флаг выставлял RELEASE=true,
# но НЕ менял ACTION, а ветка жила в `case $ACTION` — то есть была недостижима ни при
# каких аргументах: `./run.sh --release --docker-repo X --tag Y` просто поднимал
# старые образы, сообщая об успехе. Сборка релиза, в которую она вела, тоже удалена
# (см. build.sh).
STATE_DIR=".run-state"
NGINX_TEMPLATES_DIR="../infra/nginx/templates"

# Функция вывода справки
show_help() {
    head -50 "$0" | tail -45 | sed 's/^# //' | sed 's/^#//'
    exit 0
}

# Функции логирования
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

compute_templates_fingerprint() {
    if [ ! -d "$NGINX_TEMPLATES_DIR" ]; then
        echo ""
        return 0
    fi

    find "$NGINX_TEMPLATES_DIR" -type f | sort | while IFS= read -r file_path; do
        sha256sum "$file_path"
    done | sha256sum | awk '{print $1}'
}

nginx_service_exists() {
    "${COMPOSE_CMD[@]}" config --services 2>/dev/null | grep -qx "nginx"
}

# Сверка набора ключей .env.<mode> с образцом .env.example.
#
# ⚠️ ЭТА ПРОВЕРКА ПРИНЦИПИАЛЬНО НЕ МОЖЕТ ЖИТЬ В CI: `.env.dev`/`.env.prod` —
# gitignored и на раннер не попадают, а джоба `integration` вдобавок подменяет их
# копией `.env.example`, то есть сверяет файл сам с собой. Единственное место, где
# настоящий файл существует, — деплой-хост. Отсюда и вызов здесь, а не отдельной
# целью Makefile: цель, которую надо помнить, забудут.
#
# Что это ловит: ключ добавили в `.env.example`, а в `.env.prod` не перенесли —
# сервис молча уезжает на дефолт из кода. Так `AGENTS__ENGINE_MODE` пропал из прода
# и оставил его в режиме, который движок отвергает. Предупреждение, а не отказ:
# лишний ключ в образце не повод не поднять стек.
check_env_drift() {
    local example=".env.example"
    [ -f "$example" ] || return 0

    local missing
    missing=$(comm -23 \
        <(grep -oE '^[A-Z_0-9]+=' "$example" | tr -d '=' | sort -u) \
        <(grep -oE '^[A-Z_0-9]+=' "$ENV_FILE" | tr -d '=' | sort -u))

    if [ -n "$missing" ]; then
        log_warning "В $ENV_FILE нет ключей, объявленных в $example:"
        echo "$missing" | sed 's/^/    /'
        log_warning "Эти настройки уйдут на дефолт из кода. Проверьте, что так и задумано."
    fi
}

# Парсинг аргументов
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            MODE="dev"
            MODE_EXPLICIT=true
            shift
            ;;
        --prod)
            MODE="prod"
            MODE_EXPLICIT=true
            shift
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --restart)
            ACTION="restart"
            shift
            ;;
        --logs)
            ACTION="logs"
            shift
            # Проверяем, есть ли следующий аргумент и не является ли он опцией
            if [[ $# -gt 0 && ! "$1" =~ ^-- ]]; then
                LOG_SERVICE="$1"
                shift
            fi
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            log_error "Неизвестная опция: $1"
            echo "Используйте --help для справки"
            exit 1
            ;;
    esac
done

# Авто-определение режима для read-only действий, если режим явно не указан.
# Это помогает командам --logs/--status корректно работать после запуска в --prod.
detect_active_mode() {
    local dev_running=false
    local prod_running=false

    if docker compose --env-file .env.dev -p aspa-dev -f docker-compose.dev.yaml --profile dev --profile celery ps --status running -q 2>/dev/null | grep -q .; then
        dev_running=true
    fi

    if docker compose --env-file .env.prod -p aspa-prod -f docker-compose.yaml --profile prod --profile celery ps --status running -q 2>/dev/null | grep -q .; then
        prod_running=true
    fi

    if [ "$prod_running" = true ] && [ "$dev_running" = false ]; then
        MODE="prod"
        log_info "Авто-режим: обнаружены запущенные prod-сервисы, использую --prod"
    elif [ "$dev_running" = true ] && [ "$prod_running" = false ]; then
        MODE="dev"
        log_info "Авто-режим: обнаружены запущенные dev-сервисы, использую --dev"
    fi
}

if [ "$MODE_EXPLICIT" = false ] && { [ "$ACTION" = "logs" ] || [ "$ACTION" = "status" ]; }; then
    detect_active_mode
fi

# Определение compose файла
if [ "$MODE" = "dev" ]; then
    COMPOSE_FILE="docker-compose.dev.yaml"
    PROJECT_NAME="aspa-dev"
else
    COMPOSE_FILE="docker-compose.yaml"
    PROJECT_NAME="aspa-prod"
fi
ENV_FILE=".env.${MODE}"
select_application_compose

APP_DOMAIN=${APP_DOMAIN:-${APP__DOMAIN:-${SERVICE__APP_DOMAIN:-""}}}

if [ -z "$APP_DOMAIN" ] && [ -f "$ENV_FILE" ]; then
    APP_DOMAIN=$(awk -F= '
        /^[[:space:]]*(APP_DOMAIN|APP__DOMAIN|SERVICE__APP_DOMAIN)=/ {
            key=$1
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
            value=substr($0, index($0, "=")+1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            gsub(/^"|"$/, "", value)
            gsub(/^\047|\047$/, "", value)
            domain=value
        }
        END { if (domain != "") print domain }
    ' "$ENV_FILE")
fi

APP_DOMAIN=${APP_DOMAIN:-"localhost"}

# Опциональные тяжёлые стеки — только по флагу (сабмодули MemOS/local-deep-research
# должны быть инициализированы). Пример: MEMOS=1 LDR=1 ./docker/run.sh --dev
EXTRA_PROFILES=()
[ "${MEMOS:-0}" = "1" ] && EXTRA_PROFILES+=(--profile memos)
[ "${LDR:-0}" = "1" ] && EXTRA_PROFILES+=(--profile ldr)

COMPOSE_CMD=(docker compose --env-file "$ENV_FILE" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" --profile "$MODE" --profile celery "${EXTRA_PROFILES[@]}")

# Функция остановки сервисов
stop_services() {
    log_info "Остановка сервисов..."

    "${COMPOSE_CMD[@]}" down

    # Удаление временного .env файла
    if [ -f ".env" ]; then
        rm .env
        log_info "Удален временный .env файл"
    fi

    log_success "Все сервисы остановлены"
}

# Функция показа логов
show_logs() {
    if [ -n "$LOG_SERVICE" ]; then
        log_info "Логи сервиса $LOG_SERVICE (Ctrl+C для выхода)..."
    "${COMPOSE_CMD[@]}" logs -f "$LOG_SERVICE"
    else
        log_info "Логи всех сервисов (Ctrl+C для выхода)..."
    "${COMPOSE_CMD[@]}" logs -f
    fi
}

# Функция показа статуса
show_status() {
    log_info "Статус основных сервисов:"
    "${COMPOSE_CMD[@]}" ps
}

# Подготовка до запуска и до остановки работающего стека при --restart.
prepare_startup_configuration() {
    if [ ! -f "$COMPOSE_FILE" ] || [ ! -f "$ENV_FILE" ]; then
        log_error "Нет $COMPOSE_FILE или $ENV_FILE; подготовьте конфигурацию окружения."
        return 1
    fi
    prepare_runtime_environment
    production_simulation_preflight
    check_env_drift
    validate_startup_configuration
    prepare_local_llm_model "${COMPOSE_CMD[@]}"
}

# Функция запуска сервисов
validate_startup_configuration() {
    # Do not print dotenv/parser diagnostics: malformed values may be private.
    # Startup has no build placeholder and fails closed on missing secrets.
    if ! compose_config_preflight "${COMPOSE_CMD[@]}"; then
        exit 1
    fi
}

start_compose_services() {
    local status
    # Терминал принадлежит Docker: без фильтра, pipe, буфера и ожидания healthcheck.
    if "${COMPOSE_CMD[@]}" up -d "$@"; then
        return 0
    else
        status=$?
        log_error "Команда запуска Docker завершилась ошибкой; code=compose_up_failed"
        return "$status"
    fi
}

start_services() {
    log_info "============================================"
    log_info "Startup"
    log_info "============================================"
    log_info "Режим: $MODE"
    log_info "Compose файл: $COMPOSE_FILE"
    log_info "Compose project: $PROJECT_NAME"
    log_info "============================================"

    # Проверка наличия compose файла
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "Файл $COMPOSE_FILE не найден!"
        log_info "Сначала выполните: ./build.sh --$MODE"
        exit 1
    fi

    # Проверяем env файл для интерполяции переменных
    if [ ! -f "$ENV_FILE" ]; then
        log_error "Файл $ENV_FILE не найден!"
        exit 1
    fi

    # Запуск основного стека
    log_info ""
    log_step "Запуск основного стека..."

    mkdir -p "$STATE_DIR"

    local templates_fingerprint
    templates_fingerprint=$(compute_templates_fingerprint)
    local templates_state_file="${STATE_DIR}/nginx-templates-${MODE}.sha256"
    local force_recreate_nginx=false

    if [ -n "$templates_fingerprint" ] && nginx_service_exists; then
        if [ -f "$templates_state_file" ]; then
            local previous_fingerprint
            previous_fingerprint=$(cat "$templates_state_file")
            if [ "$previous_fingerprint" != "$templates_fingerprint" ]; then
                force_recreate_nginx=true
                log_warning "Обнаружены изменения в infra/nginx/templates/* — nginx будет пересоздан (--force-recreate nginx)"
            fi
        elif "${COMPOSE_CMD[@]}" ps -q nginx 2>/dev/null | grep -q .; then
            force_recreate_nginx=true
            log_warning "Не найден state шаблонов nginx для режима ${MODE}, но nginx уже существует — выполняю первичную синхронизацию (--force-recreate nginx)"
        fi
    fi

    if [ "$force_recreate_nginx" = true ]; then
        start_compose_services --force-recreate nginx
        start_compose_services
    else
        start_compose_services
    fi

    if [ -n "$templates_fingerprint" ]; then
        echo "$templates_fingerprint" > "$templates_state_file"
    fi

    # Вывод информации о доступе
    log_info ""
    log_info "============================================"
    log_success "Команда запуска Docker выполнена. Готовность сервисов не проверялась."
    log_info "============================================"
    log_info ""
    log_info "Доступные адреса:"

    if [ "$MODE" = "prod" ]; then
        local public_port public_origin
        public_port=$(environment_value PUBLIC_HTTPS_PORT 443)
        public_origin="https://${APP_DOMAIN}"
        [ "$public_port" = "443" ] || public_origin="${public_origin}:${public_port}"
        log_info "  Frontend:    ${public_origin}"
        log_info "  Backend API: ${public_origin}/api"
    else
        local frontend_port backend_port minio_console_port
        frontend_port=$(environment_value FRONTEND_PORT 3000)
        backend_port=$(environment_value BACKEND_PORT 8000)
        minio_console_port=$(environment_value MINIO_CONSOLE_PORT 9001)
        log_info "  Frontend:    http://localhost:${frontend_port}"
        log_info "  Backend API: http://localhost:${backend_port}"
        log_info "  API Docs:    http://localhost:${backend_port}/api/docs"
        log_info "  MINIO UI:    http://localhost:${minio_console_port}"

    fi

    log_info ""
    log_info "Команды:"
    log_info "  Логи:        ./docker/run.sh --logs"
    log_info "  Статус:      ./docker/run.sh --status"
    log_info "  Остановка:   ./docker/run.sh --stop"
    if [ "$RUN_TPOT" = true ]; then
        log_info "  Остановка всего: ./run.sh --stop --tpot"
    fi
}

# Выполнение выбранного действия
case $ACTION in
    start)
        prepare_startup_configuration
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        prepare_startup_configuration
        stop_services
        echo ""
        start_services
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
esac
