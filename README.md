# Research knowledge base

Самодостаточный контур сбора, проверки и выдачи доказательной базы по диссертации.
Каталог совмещает канонические научные данные, воспроизводимый curation pipeline,
read-only HTTP API, CLI, тесты и Docker-образ. Для работы ему не нужны `backend`,
`agents` или другие соседние директории.

## Текущий статус корпуса

- 214 канонических карточек и 271 алиас с сохранённой трассируемостью;
- 43 активных и 11 выведенных из обращения кластеров;
- 109 программных, инфраструктурных и dataset-ресурсов в `data/ST.json`;
- все 109 ресурсов `ST.json` имеют стабильные `STNNN` ID и решения после партий
  `st-batch-001`–`st-batch-007` и последующих проверок: 72 `verified_primary`, 19 `partially_verified`,
  18 `rejected`, незавершённых ресурсов нет;
- 46 полных избыточных копий удалено при миграции исходных 410 записей;
- relevance‑5 закрыт на уровне решений: 45 `verified_primary`, 3 `verified_metadata`,
  10 `partially_verified`, 3 `rejected`, ноль `unverified/pending`;
- relevance‑4 закрыт: 46 `verified_primary`, 3 `verified_metadata`,
  9 `partially_verified`, 15 `rejected`;
- relevance‑3 закрыт: 17 `verified_primary`, 0 `verified_metadata`,
  3 `partially_verified`, 2 `rejected`;
- во всём реестре нет `unverified/pending`; научный шлюз остаётся `G0_REVISE`
  до авторского просмотра матрицы доказательств и отдельного решения руководителя.
- шесть GitHub-кандидатов симуляции Drosophila обработаны 23.09.2026: четыре
  опубликованы как новые code entities (`S732`, `S733`, `S734`, `S737`), две
  существующие карточки актуализированы (`S200`, `S292`) без создания дублей.
- schema 2.0 терминально разрешает все nullable-поля: необъяснённых `unknown`,
  пустых строк и `null` нет; причина, дата и locator записаны в `field_resolution`;
- добавлены `S738`–`S747`, неранжированный каталог из 15 классов новизны и единый
  рабочий паспорт Drosophila × ECAP × SCS; шлюз остаётся `G0_REVISE`.
- `S746` фиксирует существенный патентный prior art: синтетические ECAP,
  growth-curve-разметку и encoder–decoder-предобучение для удаления артефакта;
  патент не считается эмпирической проверкой и не содержит Drosophila-моста.
- `S747` отделяет первичный эксперимент от вторичного briefing `S001`: система
  связывает классификацию нейронной реакции крысы с адаптивной SCS, но использует
  случайное разбиение записей шести животных, не ECAP и не человеческую валидацию.
- `S764` добавляет первичный физический ECAP forward model с направленными
  электродами к потоку NS-07; расчёт ECAP через проводящую среду и reciprocity
  уже является prior art, а клинический исход и перенос от Drosophila в работе
  не проверяются.
- `S765` фиксирует сравнение экспоненциальной и полиномиальной коррекции
  артефакта ECAP на записях двух пациентов. Это технический аналог NS-08;
  20 повторных наблюдений не означают 20 независимых пациентов.
- `S766` фиксирует раннюю физическую модель ECAP: FEM, модели аксонов и
  расчёт записи по принципу взаимности. Сравнение с опубликованной
  клинической кривой не является проверкой прогноза на новых пациентах.
- `S767` разделяет 284 анализируемые кривые ECAP у 45 пациентов и модельный
  расчёт активации волокон: одинаковая амплитуда ECAP не гарантирует
  одинакового числа активированных волокон при разной геометрии записи.
- `S768` фиксирует опубликованную в 2021 году модель ECAP через проводящую
  среду, модели волокон и сумму потенциалов одиночных волокон; результаты
  относятся к симуляции без независимой клинической проверки.

Точная оценка на любой момент:

```powershell
uv sync --extra dev
uv run --frozen researchctl validate
uv run --frozen researchctl stats
uv run --frozen researchctl completeness
uv run --frozen researchctl novelty-check
```

## Научная граница

База сознательно различает:

1. ноксический стимул и измеримую ноцицептивную/защитную реакцию Drosophila;
2. перенос синтетического предобучения на независимые человеческие pain datasets;
3. отдельную клиническую проверку прогноза ответа на SCS по человеческим данным.

Симуляционная метка не называется субъективной «болью», тело мухи не считается
моделью спинного мозга без отдельного отображения, а ECAP не трактуется как прямая
мера боли. Если человеческих SCS/ECAP-данных с исходами нет, третий уровень остаётся
перспективой, а не результатом.

## Устройство

| Артефакт | Назначение |
|---|---|
| `data/records.json` | Канонический реестр публикаций и наборов данных |
| `data/aliases.json` | Стабильные ссылки от удалённых дублей к каноническим ID |
| `data/clusters.json` | Тематические представления и очередь некластеризованных записей |
| `data/ST.json` | Инструменты, модели, репозитории и dataset-ресурсы |
| `data/source-record.schema.json` | Структурный контракт карточки |
| `data/vocabularies.json` | Контролируемые статусы, конструкты, роли и риск-флаги |
| `data/archive/` | Два последних снимка отката с SHA-256; базовые срезы миграции сохранены отдельно |
| `data/audit-report.json` | Результат конкретного аудиторского прохода |
| `data/validation-log.json` | Проверенные утверждения и ограничения первичных источников |
| `data/evidence-matrix.json` | Трассировка тезисов, доказательств, ограничений и допустимых выводов |
| `data/evidence-review-ledger.json` | Сводный журнал 27 проверок локаторов и исправлений матрицы |
| `data/scientific-contract.json` | Машинный контракт сущностей, переходов, ECAP-like тракта и STOP-критериев |
| `data/human-dataset-matrix.json` | Аудит доступа, модальностей и несовместимых целевых переменных человеческих наборов |
| `data/human-ecap-scs-access-audit.json` | Проверка доступа, согласия, связи ECAP с пациентом и клинических исходов у SCS-кандидатов |
| `data/completeness-report.json` | Счётчики терминального разрешения полей schema 2.0 |
| `data/ecap-scs-audit.json` | Первично локализованные выборки, геометрия, стимуляция, разбиения и метрики опорных ECAP/SCS-источников |
| `data/synthetic-domain-audit.json` | Происхождение реальных данных, контроль утечки, единица разбиения и граница внешнего теста для synthetic/domain источников |
| `data/ns06-prior-art-audit.json` | Механизмы synthetic-pain аналогов, границы сравнения с S149 и состояние цитатного поиска |
| `data/scs-outcome-audit.json` | Роли ECAP, других биомаркеров, клинических исходов и независимой проверки прогноза SCS |
| `data/ns11-prediction-audit.json` | Открытый NS-11: target, follow-up и связь данных на уровне пациента для проверенных аналогов |
| `data/search-protocol.json` | Prior-art потоки и критерий насыщения поиска |
| `data/novelty-landscape.json` | Неранжированный морфологический каталог новизны |
| `data/dissertation-concept.json` | Тема, цель, гипотеза и трассируемые положения |
| `data/runtime-audit.json` | Воспроизводимый запуск и терминальные решения по симуляторам |
| `docs/scientific-contract.md` | Человекочитаемая версия научного контракта |
| `data/curation/relevance-{3,4,5}/` | Очереди, партии, решения и registry-search проходов всех уровней релевантности |
| `data/staging/` | Шаблон и локальная очередь новых карточек |
| `migrations/` | Одноразовые воспроизводимые преобразования исторических снимков |
| `service/` | HTTP API, CLI, integrity gate и lifecycle pipeline |
| `SKILL.md` | Регламент для будущих агентных проходов по сбору и валидации |

Архитектура подробно описана в [docs/architecture.md](docs/architecture.md), контракт
карточки — в [docs/data-contract.md](docs/data-contract.md), процесс пополнения — в
[docs/curation-workflow.md](docs/curation-workflow.md).

## CLI

После `uv sync --extra dev` доступна одна команда `researchctl`:

```powershell
# Полный блокирующий контроль данных и архивных хешей
uv run --frozen researchctl validate

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

Скопируйте `data/staging/source-record.template.json` в `data/staging/inbox`, заполните карточку
и выполните:

```powershell
# Безопасно создать заготовку со следующим свободным ID
uv run --frozen researchctl new "Exact source title" --output data/staging/inbox/source.json

# Схема, словари, коллизии ID, полные дубли и совпадения названий; без записи
uv run --frozen researchctl stage data/staging/inbox/batch.json

# Тот же publish-план, всё ещё без записи
uv run --frozen researchctl publish data/staging/inbox/batch.json

# Явная публикация после ручного review
uv run --frozen researchctl publish data/staging/inbox/batch.json --apply
```

Перед записью автоматически создаётся полный снимок. Новые карточки попадают в
`unclustered_record_ids`; кластеризация не угадывается автоматически.

## Локальный MCP для Codex

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

Научный контракт доступен как `research://scientific-contract`, а подробная матрица
человеческих наборов — как `research://human-dataset-matrix`. Они отделяют симуляцию,
перенос на человеческие целевые переменные и условную SCS-проверку и не меняют статус
`G0_REVISE` без авторского и руководительского решения.

Сервер не предоставляет произвольное чтение файлов, запись вне `data/staging`/`data/curation`
или запуск команд. Публикация использует те же snapshot, atomic write и post-write integrity gate,
что и `researchctl`. CLI остаётся равноправным fallback для CI, ручной работы и восстановления.
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
- unit/transport tests.

Те же три gate описаны в локальном `.pre-commit-config.yaml`; после установки
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
