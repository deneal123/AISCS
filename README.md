# Локальная CPU-модель GPTHub

Отдельный inference-сайдкар на llama.cpp, без PyTorch/CUDA и собственного executor.
OpenAI-совместимые `/v1/models`, `/v1/chat/completions`, SSE и function calling
предоставляет ограниченный JSON-шлюз перед закреплённым llama-server. Модель — официальный
`LiquidAI/LFM2.5-1.2B-Instruct-GGUF`, Q4_K_M,730895168 байт.

Модель и runtime проверяются SHA256. Скачивание происходит только в отдельной
операции подготовки. Inference использует read-only volume и внутреннюю сеть без
выхода в интернет. У процесса нет Docker socket, проекта, БД, shell/MCP-инструментов
или новых прав. Ключ обязателен, в аргументы процесса не передаётся.

## Структурированный транспорт

Шлюз слушает8080, дочерний llama-server — только loopback8081 внутри контейнера.
Схемы разрешённых инструментов компилируются в ограниченную JSON schema; результат
проверяется до преобразования в OpenAI tool call. Режимы auto/required/именованный
выбор не расширяют список разрешённых инструментов. Невалидный или усечённый ответ
не исполняется, известный usage сохраняется; скрытого повторного inference нет.

SSE буферизуется до окончания и проверки ответа, а не передаёт токены в реальном
времени. Отправляются стандартные delta/finish chunks и один usage receipt. Это
сознательная граница первой поставки. Одновременно допускается один inference;
занятый сервер возвращает429 без скрытой очереди.

На реальном CPU пройдены три независимых корпуса по16 последовательных циклов
«инструмент → непрогнозируемый результат → проверенный ответ»: auto, required и
именованный выбор. Каждый корпус содержит32 обращения к модели. Отдельно проверены
настоящий реестр провайдеров, admission и OpenAI SDK. Это не заменяет сквозную
приёмку IDE/PDF через worker и долговечный журнал.

## Запуск на dev

Сервис — отдельный подмодуль суперпроекта, ветка `local_llm` того же репозитория,
как у остальных сайдкаров. После клонирования суперпроекта:
`git submodule update --init --recursive local_llm`.

## Структура сервиса

- `service/main.py` — сборка зависимостей и запуск; `configuration.py` — проверка настроек.
- `service/application/inference.py` — один ограниченный сценарий вывода модели.
- `service/domain/protocol/` — проверка входа, компиляция схем, transcript и ответ.
- `service/domain/model.py` — закреплённые параметры модели и runtime.
- `service/infrastructure/llama/` — транспорт и жизненный цикл llama.cpp.
- `service/infrastructure/models/` — проверяемая загрузка весов.
- `service/presentation/http.py` — HTTP, авторизация и OpenAI-совместимый API.
- `scripts/provision_model.py` — подготовка весов; `scripts/acceptance/` — диагностика.
- `tests/` — регрессии; `docker/` — сборка непривилегированного runtime.

Проверки из каталога суперпроекта:
`uv run --project local_llm --extra dev pytest -q local_llm/tests` и
`uv run --project local_llm --extra dev ruff check local_llm`.
Изолированные проверки HTTP не требуют весов, Docker или платных API.

## Настройка и развёртывание

Штатный путь из корня суперпроекта: `make build` и `make run` для dev,
`make build MODE=prod` и `make run MODE=prod` для production. Дополнительный профиль
не требуется: inference входит в обычное ядро, downloader вызывается сборкой отдельно.
Веса скачиваются в постоянный Docker volume, проверяются по размеру и SHA256;
проверенный кеш повторно не скачивается даже при пересборке образов без кеша.

При `make run` существующий скрипт синхронизации env создаёт отсутствующий
`LOCAL_LLM_API_KEY` и согласует `AGENTS__LOCAL_API_KEY`, не меняя рабочие секреты.
Потребуется Python 3 на хосте. После проверки кеша скрипт дожидается healthy
локальной модели перед запуском остальных сервисов. Ошибка подготовки запрещает
успешный startup; `--status`, `--logs` и `--stop` ничего не скачивают и не меняют env.

Низкоуровневые команды для отдельной диагностики (ключи должны быть подготовлены):

```powershell
docker compose --project-name gpthub-dev --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile local-llm build local-llm
docker compose --project-name gpthub-dev --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile local-llm-setup run --rm --no-deps local-llm-model
docker compose --project-name gpthub-dev --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile local-llm up -d --no-deps local-llm
```

API доступен контейнеру agents по `http://local-llm:8080/v1`, без публикации на хост.
На текущем Docker Engine `internal`-сеть не создаёт внешний слушатель даже при
заявленном ports; такая декларация удалена, а не выдана за рабочий localhost API.
Для приложения используется существующий шлюз agents. `/health` проверяет готовность
runtime, но не доказывает правильность tool calling. Остальные сервисы эти команды
не пересоздают. С хоста реальную CPU-пробу запускает `python scripts/local_llm_probe.py`:
транспорт идёт из существующей сети agents, секрет передаётся только через stdin.

`--admission --admission-profile concise` запускает отдельную read-only диагностику
контракта на синтетических IDE-запросах: ясный файл, анализ и настоящий недостающий
параметр. Не создаёт задания или файлы и не принимает новую инструкцию автоматически.
Код выхода0 означает завершение диагностики, а не качество: проверять matched_cases
и case_count. Лимит — два protocol calls на случай и300с на весь корпус. Непустой
question при false, выдуманный файл или пропущенное решение пользователя не засчитываются.
Профиль `both` сохраняет исходное сравнение baseline/concise; `guided` выбирается
отдельно, `all` явно включает все три. Типы диагностик CLI взаимоисключающие.

Лимиты начального профиля:2 CPU threads,1 slot,8192 токена общего контекста,1536МБ
контейнера. Поддерживается контекст до32768, но увеличение требует ресурсов и
соответствующего admission/context budget. Нельзя заявлять32768 доступных токенов,
когда фактический runtime запущен с8192. Загрузка не исправляет и не перезаписывает
неизвестный существующий файл. Оставшийся lock требует явной сверки владельца.

## Лицензия и приёмка

Runtime — llama.cpp/MIT; веса — Liquid AI LFM Open License. Условия использования
модели проверяются отдельно по [лицензии издателя](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct/blob/main/LICENSE).
Русский не заявлен среди основных языков; разработчик не рекомендует модель для
программирования. GPTHub обязан проверить реальные IDE/PDF-задачи и честно показывать
непройденный критерий, а не обещать качество большой облачной модели.

План и фактические результаты:
[HARNESS2_LOCAL_MODEL_PLAN.md](../docs/HARNESS2_LOCAL_MODEL_PLAN.md).
