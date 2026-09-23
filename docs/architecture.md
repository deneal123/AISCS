# Архитектура research sidecar

## Границы

Сайдкар обслуживает реестр источников и производные представления. Он не делает
научные выводы автоматически, не подтверждает перенос между видами и не изменяет
корпус через HTTP. Публичный контур намеренно read-only.

```text
candidate JSON
    |
    v
researchctl stage  -- схема, словари, ID, дубликаты, provenance
    |
    v
ручное решение скрининга
    |
    v
researchctl publish -- pre-change snapshot + atomic JSON writes + integrity gate
    |
    +--> data/records.json / data/aliases.json
    +--> data/clusters.json (новые записи сначала unclustered)
    +--> HTTP API / JSONL export
```

## Слои

- `service/contracts.py` — стабильные имена сервиса, версия, endpoints и коды ошибок.
- `service/core.py` — загрузка JSON, кеш по mtime/size, поиск, алиасы, сводки и экспорт.
- `service/integrity.py` — независимый от FastAPI блокирующий контроль целостности.
- `service/pipeline.py` — staging, снимки и публикация новых записей.
- `service/app.py` — тонкий HTTP-транспорт без операций записи.
- `service/mcp_server.py` — локальный stdio MCP-транспорт; мутации делегируются существующим
  pipeline/curation-функциям.
- `service/cli.py` — единая точка для человека, CI и контейнера.

## Источники истины

- `data/records.json` — канонические карточки источников;
- `data/aliases.json` — перенаправление удалённых дублей на канонический ID;
- `data/clusters.json` — тематические представления, не отдельные источники;
- `data/ST.json` — реестр программ, наборов и инфраструктурных ресурсов;
- `data/source-record.schema.json` + `data/vocabularies.json` — контракт карточки;
- `data/archive/*/manifest.json` — неизменяемые снимки и SHA-256;
- `data/audit-report.json`, `data/validation-log.json` — отчёты конкретного прохода,
  а не замена данным.
- `data/scientific-contract.json`, `data/human-dataset-matrix.json` — проверяемые
  научные границы, переходы, STOP-критерии и совместимость человеческих наборов.

## MCP-контур

Codex запускает `research-mcp` локально через `uv run --directory <research> --frozen`.
Сервер и `researchctl` используют один `ResearchRepository`, один набор integrity-проверок и
одни функции жизненного цикла. Поэтому MCP не создаёт вторую базу истины и не меняет контракт
read-only HTTP API.

```text
Codex CLI / IDE
       |
       | stdio MCP
       v
service/mcp_server.py
       |
       +--> ResearchRepository --------> records / aliases / clusters / ST / evidence
       |
       +--> pipeline + curation --------> snapshot -> atomic write -> integrity gate
                                              (только apply=true)
```

Статические MCP resources ограничены руководством, TODO, аудитом, матрицей доказательств,
научным контрактом, матрицей человеческих наборов, схемой и словарями. Динамические
resources доступны только для `source/{id}` и `cluster/{id}`.
Пользовательские пути не передаются произвольно: candidate-файлы ограничены inbox, review-
партии — `data/curation/relevance-*`, кластерные манифесты — `data/curation/cluster-assignments`.

Server instructions фиксируют научные границы: симуляционная метка не является субъективной
болью, ECAP не является прямой мерой боли, а `verified_primary` не означает независимого
воспроизведения результата.

## Эксплуатационная модель

Контейнер стартует только после полного integrity gate. `/health` сообщает контракт
и fingerprint данных, `/ready` повторно проверяет корпус. Изменение файлов требует
CLI и локального доступа к рабочей копии. Это отделяет потребителей базы знаний от
процесса научной редакции.
