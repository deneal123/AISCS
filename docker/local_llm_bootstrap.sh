#!/bin/bash
# Общая подготовка локальной модели для штатных build/run. Сервис здесь не запускается.

require_local_llm_source() {
    if [ ! -f ../local_llm/docker/Dockerfile ]; then
        printf '[ERROR] Не инициализирован local_llm. В корне проекта выполните: git submodule update --init --recursive local_llm\n' >&2
        return 1
    fi
}

prepare_runtime_environment() {
    local python_command=()
    if [ -n "${PYTHON_BIN:-}" ]; then
        python_command=("$PYTHON_BIN")
    elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
        python_command=(python3)
    elif command -v uv >/dev/null 2>&1; then
        python_command=(uv run --no-project --python 3.13)
    else
        printf '[ERROR] Для безопасной подготовки env требуется Python 3; code=env_python_required\n' >&2
        return 1
    fi
    # Генерируются только отсутствующие известные секреты; рабочие значения сохраняются.
    local generator_option=()
    [ "${SERVICE_APPLICATION_PROFILE:-gpthub}" = "simulation" ] && generator_option=(--provision-generator-secret)
    "${python_command[@]}" ./sync_env.py --mode "$MODE" \
        --provision-coordination-secret --provision-local-llm-secret "${generator_option[@]}"
}

prepare_local_llm_model() {
    # Numerical demo is independent from LLM weights; preserve the full upstream path on opt-in.
    if [ "${SERVICE_APPLICATION_PROFILE:-gpthub}" = "simulation" ] && [ "${ENABLE_LOCAL_LLM:-0}" != "1" ]; then
        return 0
    fi
    local diagnostic code line
    printf '[INFO] Подготовка Qwen2.5-1.5B: проверка кеша; при отсутствии — загрузка 1,12 ГБ с проверкой SHA256.\n'
    # Используется уже собранный образ, тот же project/env и тот же постоянный volume.
    # Не запускаем зависимости или inference, не выдаём downloader секретов провайдеров.
    if ! diagnostic=$("$@" --profile local-llm-setup run --rm --no-deps -T local-llm-model 2>&1); then
        code=local_llm_model_setup_failed
        # Только закрытые коды downloader; диагностика Docker может содержать секреты.
        while IFS= read -r line; do
            case "$line" in
                model_cache_conflict|model_download_busy|model_download_limit|model_digest_mismatch|model_download_unavailable)
                    code="$line" ;;
            esac
        done <<< "$diagnostic"
        printf '[ERROR] Модель не подготовлена; code=%s. Проверьте сборку (make build MODE=%s), доступ к загрузке и кеш; существующие веса не удалялись.\n' "$code" "$MODE" >&2
        return 1
    fi
    printf '[OK] Кеш локальной модели проверен; веса остаются вне Git и образа.\n'
}
