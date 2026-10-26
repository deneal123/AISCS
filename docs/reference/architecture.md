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

Пакет `service/` разделён по ответственности. Зависимости направлены в одну сторону:
`common` ← `registry` ← `curation` ← `interfaces` и `indexing` ← `knowledge`, `library` ←
`interfaces`.

- `common/` — утилиты без предметной логики: исключения (`errors`), строгое чтение и
  атомарная запись JSON (`jsonio`), атомарная запись файлов (`files`), SHA-256 (`hashing`),
  время (`clock`), декодирование текста (`text`).
- `registry/` — канонический реестр: раскладка файлов (`layout`), кешируемый read-only
  `ResearchRepository` (`repository`), идентификаторы (`ids`), полнота schema 2.0
  (`completeness`), каталог новизны (`novelty`) и блокирующий контроль целостности
  (`validation/`: карточка, тематические аудиты, научный контракт, общий шлюз).
- `curation/` — запись в реестр: кандидаты для stage/publish (`candidates`), снимки отката
  (`snapshots`), партии relevance-обзора (`sources`), кластеры (`clusters`), ресурсы ST
  (`resources`) и чтение применённых партий (`batches`).
- `indexing/` — общая инфраструктура поисковых индексов: настройки, эмбеддинги с кэшем,
  Neo4j/Qdrant, поколения (`GenerationStore`, `index_vectors`), проверка ID бэкендов,
  переносимые снимки, чанкинг и ограниченная HTTP-загрузка.
- `knowledge/` — индекс доказательств по статьям: проекция реестра, корпус (`corpus/`: разбор,
  идентичность, кандидаты, чанки, подготовка), извлечения, движок поиска, проверки, снимок.
- `library/` — индекс методических книг: каталог, нормализаторы форматов (`formats/`),
  подготовка, проекция и движок.
- `interfaces/` — транспорты и контракт: `researchctl` (`cli`), read-only HTTP (`http`), stdio
  MCP (`mcp`), стабильные имена, версия, endpoints и коды ошибок (`contracts`).

Вне пакета: `scripts/` — проверки, smoke, запуск и регистрация MCP; `scripts/history/` —
разовые скрипты наполнения сентября 2026 года; `migrations/` — датированные воспроизводимые
преобразования. `scripts/check_imports.py` следит, чтобы их импорты `service.*` разрешались,
а `scripts/check_reproducibility.py` — чтобы снимки пересобирали записанные поколения.

## Источники истины

- `data/records.json` — канонические карточки источников;
- `data/aliases.json` — перенаправление удалённых дублей на канонический ID;
- `data/clusters.json` — тематические представления, не отдельные источники;
- `data/ST.json` — реестр программ, наборов и инфраструктурных ресурсов;
- `data/schema/source-record.schema.json` + `data/schema/vocabularies.json` — контракт карточки;
- `.work/research-snapshots/*/manifest.json` — два последних автоматических снимка отката с SHA-256;
- `data/archive/*/manifest.json` — базовые срезы миграции и явно запрошенные постоянные снимки;
- `data/audits/summary/audit-report.json`, `data/audits/summary/validation-log.json` — отчёты конкретного прохода,
  а не замена данным.
- `data/research/scientific-contract.json`, `data/evidence/human-dataset-matrix.json` — проверяемые
  научные границы, переходы, STOP-критерии и совместимость человеческих наборов.
- `data/audits/summary/completeness-report.json` — нулевой остаток необъяснённых полей;
- `data/audits/search/search-protocol.json`, `data/research/novelty-landscape.json` и
  `data/research/dissertation-concept.json` — prior-art протокол, каталог классов и единый паспорт.
- `data/audits/drosophila/runtime-audit.json` — исполнимые проверки и решения по стеку симуляции.

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
service/interfaces/mcp.py
       |
       +--> ResearchRepository --------> records / aliases / clusters / ST / evidence
       |
       +--> curation ------------------> snapshot -> atomic write -> integrity gate
       |                                     (только apply=true)
       |
       +--> knowledge / library -------> поколения индексов (Neo4j + Qdrant), только чтение
```

Статические MCP resources ограничены руководством, TODO, аудитом, матрицей доказательств,
научным контрактом, полнотой, поисковым протоколом, каталогом новизны, рабочим паспортом,
матрицей человеческих наборов, схемой и словарями. Динамические
resources доступны только для `source/{id}` и `cluster/{id}`.
Пользовательские пути не передаются произвольно: candidate-файлы ограничены inbox, review-
партии — `data/curation/relevance-*`, кластерные манифесты — `data/curation/cluster-assignments`.

Server instructions фиксируют научные границы: симуляционная метка не является субъективной
болью, ECAP не является прямой мерой боли, а `verified_primary` не означает независимого
воспроизведения результата.

## Эксплуатационная модель

Команды CLI, MCP, HTTP и Docker поддерживаются в [эксплуатационном справочнике](operations.md).

Контейнер стартует только после полного integrity gate. `/health` сообщает контракт
и fingerprint данных, `/ready` повторно проверяет корпус. Изменение файлов требует
CLI и локального доступа к рабочей копии. Это отделяет потребителей базы знаний от
процесса научной редакции.
