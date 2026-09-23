#!/bin/bash
set -e

# ============================================================================
# MLservice Build Script
# ============================================================================
#
# Использование:
#   ./build.sh [OPTIONS]
#
# Опции:
#   --dev          Сборка для режима разработки (по умолчанию)
#   --prod         Сборка для продакшн режима
#   --no-cache     Сборка без использования кэша Docker
#   -h, --help     Показать это сообщение
#
# Примеры:
#   ./build.sh                 # Сборка dev окружения
#   ./build.sh --prod          # Сборка prod окружения
#   ./build.sh --no-cache      # Пересборка без кэша
#
# ============================================================================

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Переходим в директорию скрипта
cd "$(dirname "$0")" || exit 1

# Параметры по умолчанию
MODE="dev"
NO_CACHE=""
# ⚠️ ОТСЮДА УДАЛЁН РЕЛИЗНЫЙ ПУТЬ (--docker-repo/--tag и тегирование образов).
# Он не работал НИ РАЗУ, и это было не видно: скрипт делает `cd "$(dirname "$0")"`,
# то есть CWD = docker/, а блоки тегирования стояли под `if [ -d backend ]` и
# `if [ -d frontend ]` — таких каталогов относительно docker/ нет. Даже сработай
# они, пути `-f backend/Dockerfile` неверны (реальные — backend/docker/Dockerfile),
# а отказ гасился через `|| log_warning`. В конце всё равно печаталось
# «Сборка завершена!». Публикации в реестр в проекте нет вообще — релиз надо
# заводить осознанно, а не чинить эту заглушку.

# Функция вывода справки
show_help() {
    head -30 "$0" | tail -25 | sed 's/^# //' | sed 's/^#//'
    exit 0
}

# Функция логирования
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

# Парсинг аргументов
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            MODE="dev"
            shift
            ;;
        --prod)
            MODE="prod"
            shift
            ;;
        --no-cache)
            NO_CACHE="--no-cache"
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

# Определение compose файла. PROJECT_NAME обязан совпадать с run.sh (gpthub-$MODE):
# при расхождении build собирал бы образы под чужим проектом, а run.sh пересобирал
# заново — лишняя работа и путаница в именах контейнеров.
if [ "$MODE" = "dev" ]; then
    COMPOSE_FILE="docker-compose.dev.yaml"
    PROJECT_NAME="gpthub-dev"
else
    COMPOSE_FILE="docker-compose.yaml"
    PROJECT_NAME="gpthub-prod"
fi
ENV_FILE=".env.${MODE}"

# Опциональные стеки (MemOS/LDR) — собирать только по флагу.
EXTRA_PROFILES=()
[ "${MEMOS:-0}" = "1" ] && EXTRA_PROFILES+=(--profile memos)
[ "${LDR:-0}" = "1" ] && EXTRA_PROFILES+=(--profile ldr)

log_info "============================================"
log_info "Build"
log_info "============================================"
log_info "Режим: $MODE"
log_info "Compose файл: $COMPOSE_FILE"
log_info "Compose project: $PROJECT_NAME"
if [ -n "$NO_CACHE" ]; then
    log_info "Кэш: отключен"
fi
log_info "============================================"

# Проверка наличия compose файла
if [ ! -f "$COMPOSE_FILE" ]; then
    log_error "Файл $COMPOSE_FILE не найден!"
    exit 1
fi

# Проверка наличия env файла для интерполяции docker compose
if [ ! -f "$ENV_FILE" ]; then
    log_error "Файл $ENV_FILE не найден!"
    log_error "Docker Compose не сможет корректно подставить переменные окружения."
    exit 1
fi

# 🔴 ОБРАЗ РАНТАЙМА ПЕСОЧНИЦЫ — ОТДЕЛЬНЫМ ШАГОМ, а не сервисом compose. Это не сервис:
# его никто не запускает, он лишь лежит в демоне, чтобы сайдкар мог создавать из него
# контейнеры через docker.sock. Compose-сервис ради образа завёл бы вечный «exited»
# контейнер в стеке и путал бы состояние.
#
# Без этого образа песочница поднимается на голом python-slim, где НЕТ git, — и история
# версий (`ws_log`/`ws_diff`/`ws_revert`) молча не ведётся.
WORKSPACE_RUNTIME_IMAGE="${WORKSPACE_IMAGE:-gpthub-workspace-runtime:latest}"
log_info "Сборка образа рантайма песочницы ($WORKSPACE_RUNTIME_IMAGE)..."
docker build $NO_CACHE -t "$WORKSPACE_RUNTIME_IMAGE"     -f ../workspace/docker/runtime.Dockerfile ../workspace

if [ $? -ne 0 ]; then
    log_error "Образ рантайма песочницы не собран — история версий работать не будет"
    exit 1
fi
log_success "Образ рантайма песочницы собран"

# Document Forge использует отдельный тяжёлый LaTeX-образ. Он не является сервисом:
# workspace создаёт одноразовый network=none контейнер только на время одной сборки.
DOCUMENT_RUNTIME_IMAGE="${WORKSPACE_DOCUMENT_IMAGE:-gpthub-document-runtime:latest}"
log_info "Сборка изолированного Document Forge runtime ($DOCUMENT_RUNTIME_IMAGE)..."
docker build $NO_CACHE -t "$DOCUMENT_RUNTIME_IMAGE" \
    -f ../workspace/docker/document-runtime.Dockerfile ../workspace

if [ $? -ne 0 ]; then
    log_error "Document Forge runtime не собран — PDF-конвейер недоступен"
    exit 1
fi
log_success "Document Forge runtime собран"

# Сборка основного стека
log_info "Сборка основного стека..."
# Compose expands the complete env file even for `build`, although runtime
# service secrets are neither consumed by Dockerfiles nor persisted in images.
# Keep production startup fail-closed in .env.prod while allowing image builds
# on CI/build hosts that intentionally do not hold deployment credentials.
COMPOSE_BUILD_COORDINATION_SECRET="${GPTHUB_WORKSPACE_COORDINATION_SECRET:-gpthub-compose-build-validation-only}"
GPTHUB_WORKSPACE_COORDINATION_SECRET="$COMPOSE_BUILD_COORDINATION_SECRET" \
    docker compose --env-file "$ENV_FILE" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" \
    --profile "$MODE" "${EXTRA_PROFILES[@]}" build $NO_CACHE

if [ $? -eq 0 ]; then
    log_success "Основной стек собран успешно"
else
    log_error "Ошибка сборки основного стека"
    exit 1
fi

log_info ""
log_info "============================================"
log_success "Сборка завершена!"
log_info "============================================"
log_info ""
