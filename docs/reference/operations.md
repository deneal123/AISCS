# Эксплуатация исследовательской базы

Команды выполняются из корня `research`. Это основной справочник CLI, MCP, HTTP и Docker. Научные критерии — в [TODO](../../TODO.md), данные — в [индексе](../../data/README.md).

Через MCP этот справочник доступен как `research://operations`.

## CLI

После `uv sync --extra dev` доступна одна команда `researchctl`:

```powershell
# Полный блокирующий контроль данных и архивных хешей
uv run --frozen researchctl validate

# Старые неизменяемые снимки читаются только с явным выбором прежней структуры
uv run --frozen researchctl --data-dir tests/fixtures/history/archive/2026-09-22T102852Z-pre-batch-001 validate --legacy-layout

# Сводка по статусам, ролям доказательств, конструктам и рискам
uv run --frozen researchctl stats
uv run --frozen researchctl completeness
uv run --frozen researchctl novelty-queue --status open
uv run --frozen researchctl novelty-search "closed-loop"
uv run --frozen researchctl migrate-v2  # idempotent preview; запись только с --apply

# Лексический поиск с комбинируемыми фильтрами
uv run --frozen researchctl search "ECAP" --validation-status verified_primary
uv run --frozen researchctl search --evidence-role human_validation --limit 100

# Получение записи; старый ID дубля автоматически разрешается через data/aliases.json
uv run --frozen researchctl get S063

# Экспорт для DuckDB, RAG или последующей индексации
uv run --frozen researchctl export build/sources.jsonl

# Ручной снимок всех канонических артефактов
uv run --frozen researchctl snapshot --label before-review

# Очередь и атомарное применение партии ручной валидации
uv run --frozen researchctl queue --relevance 5 --status unverified --batch-size 20
uv run --frozen researchctl review-check batch-001
uv run --frozen researchctl review-apply batch-001 --apply

# Пакетный аудит ресурсов ST.json
uv run --frozen researchctl st-queue --batch-size 15
uv run --frozen researchctl st-review-check st-batch-001
uv run --frozen researchctl st-review-apply st-batch-001 --apply
```

### Добавление источников

Создайте карточку, заполните её и выполните:

```powershell
# Безопасно создать заготовку со следующим свободным ID
uv run --frozen researchctl new "Exact source title" --output data/staging/inbox/source.json

# Схема, словари, коллизии ID, полные дубли и совпадения названий; без записи
uv run --frozen researchctl stage data/staging/inbox/source.json

# Тот же publish-план, всё ещё без записи
uv run --frozen researchctl publish data/staging/inbox/source.json

# Явная публикация после ручного review
uv run --frozen researchctl publish data/staging/inbox/source.json --apply
```

Перед записью создаётся снимок отката в игнорируемой `.work/research-snapshots/`; сохраняются два последних автоматических снимка. Новые карточки попадают в
`unclustered_record_ids`; кластеризация не угадывается автоматически.

## Локальный MCP

`aspa-research` — основной агентный интерфейс к этой базе знаний. Он работает по stdio,
читает актуальные JSON непосредственно из `data` и не требует HTTP-сервера:

```powershell
# Идемпотентная регистрация в общей локальной конфигурации Codex
.\scripts\install-codex-mcp.ps1

# Проверка сохранённой команды
codex mcp get aspa-research
codex mcp list

# Удаление регистрации
.\scripts\install-codex-mcp.ps1 -Remove
```

После добавления или удаления сервера нужно перезапустить Codex либо открыть новую сессию.
CLI и IDE используют общую конфигурацию MCP. Конфликтующая запись не заменяется автоматически:
для осознанной замены применяется `-Force`.

| Инструмент | Назначение |
|---|---|
| `status` | fingerprint, счётчики и полный integrity gate |
| `search_sources` | полнотекстовый поиск карточек и контролируемые фильтры |
| `get_source_context` | карточка, alias, кластеры, relations и evidence matrix |
| `search_resources` | поиск инструментов, датасетов и репозиториев в `ST.json` |
| `get_cluster` | кластер, опционально с развёрнутыми карточками |
| `search_evidence` | поиск тезисов, доказательств, ограничений и допустимых выводов |
| `search_novelty` | поиск по неранжированному каталогу вариантов новизны |
| `get_dissertation_concept` | единая тема, цель, гипотеза, задачи и положения |
| `save_candidate` | валидированная атомарная запись только в `data/staging/inbox` |
| `publish_candidate` | dry-run; запись только при явном `apply=true` |
| `review_batch` | check/apply существующей review-партии |
| `cluster_manifest` | check/apply манифеста из `data/curation/cluster-assignments` |
| `snapshot` | именованный неизменяемый снимок с SHA-256 manifest |

Примеры запросов агенту: «найди verified_primary источники по ECAP», «покажи контекст
S149», «найди ограничения переноса в evidence matrix». Для публикации агент сначала вызывает
`publish_candidate` без `apply`, показывает результат проверки и лишь затем повторяет вызов с
`apply=true`.

Рабочий TODO доступен как `research://todo`, история решений — как
`research://todo-decisions`. Научный контракт доступен как `research://scientific-contract`, а подробная матрица
человеческих наборов — как `research://human-dataset-matrix`. Они отделяют симуляцию,
перенос на человеческие целевые переменные и условную SCS-проверку и не меняют статус
`G0_REVISE` без отдельного решения о переходе шлюза.

Сервер не предоставляет произвольное чтение файлов или запуск команд. Запись
кандидатов ограничена `data/staging/inbox`; явная публикация и применение review
атомарно обновляют канонические данные через существующий pipeline и integrity gate.
CLI остаётся доступен для CI, ручной работы и восстановления.
HTTP API ниже по-прежнему read-only.

## HTTP API

Локальный запуск:

```powershell
.\scripts\run.ps1
```

Основные endpoints:

| Метод | Назначение |
|---|---|
| `GET /health` | Версия контракта, fingerprint корпуса, read-only declaration |
| `GET /ready` | Полный integrity gate; 503 при повреждении данных |
| `GET /v1/meta` | Метаданные всех представлений |
| `GET /v1/sources` | Поиск, фильтры, limit/offset |
| `GET /v1/sources/{id}` | Карточка с разрешением legacy alias |
| `GET /v1/clusters` | Активные кластеры; опционально retired |
| `GET /v1/evidence-summary` | Счётчики по уровням доказательства и рискам |
| `GET /v1/export/sources.jsonl` | Потоковый переносимый экспорт |

HTTP-контур не содержит POST/PUT/DELETE. Это намеренная граница: научная редакция
должна оставлять локальный снимок и проходить CLI-gates.

## Проверки

Полный локальный gate:

```powershell
.\scripts\check.ps1
```

Он выполняет в одном закреплённом окружении:

- проверку JSON, схемы, словарей, алиасов, кластеров, счётчиков и архивных SHA-256;
- Ruff для сервиса и утилит;
- unit/transport tests;
- проверку состава release-манифеста, SHA-256, ссылок, якорей и согласованности текущих решений.

Первые три gate описаны в локальном `.pre-commit-config.yaml`; после установки
окружения его можно подключить командой `pre-commit install`.

Одноразовый `migrations/rebuild_2026_09_21.py` оставлен только для воспроизводимости
первой миграции из `data/archive/2026-09-21`. Его нельзя использовать как обычный способ
пополнения: он пересобирает корпус из исходного снимка. Безопасная проверка выполняется
через `python migrations/rebuild_2026_09_21.py --check`; запись требует явного
`--output-dir`, а перезапись рабочих данных — отдельного опасного флага `--apply`.

## Docker

```powershell
docker build -t aspa-research-sidecar -f docker/Dockerfile .
docker run --rm -p 8091:8080 aspa-research-sidecar
# или автономный hardened Compose
docker compose up --build
```

Образ запускается от непривилегированного пользователя и перед HTTP-сервером
выполняет integrity gate. Канонические данные включены в образ и доступны только
для чтения на уровне API. Для локального live-корпуса можно явно примонтировать
каталог в `/data:ro`.
