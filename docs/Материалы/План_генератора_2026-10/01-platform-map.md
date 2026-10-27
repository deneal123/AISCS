# Карта переиспользования платформы

Основание: чтение исходников 27.10.2026, включая три адресные проверки Pi и сверку ключевых выводов основным агентом. Это статический аудит; установки, запуска сервисов и испытаний их совместной работы не было. README используется как указатель, исполняемый код — для проверки наличия функции.

## Платформенное ядро

| Компонент и первичный локатор | Подтверждено по коду | Решение для генератора |
|---|---|---|
| [Сборка инфраструктуры backend](../../../backend/service/composition/infra.py), `build_infra` | PostgreSQL, Redis/cache/sessions, Celery, потоки событий, файловое хранилище | Переиспользовать композицию и жизненный цикл; включать нужные зависимости профилем |
| [PostgreSQL](../../../backend/service/infrastructure/database/postgresql.py), `PgConnector`; [миграции](../../../backend/alembic/versions/) | SQLAlchemy-сессии, управление соединениями, Alembic | Добавить доменные записи симуляции в ту же БД; отдельную БД и инструмент миграций не создавать |
| [Кэш](../../../backend/service/infrastructure/cache/cache.py), `RedisCacheService`; [RedisManager](../../../backend/service/infrastructure/cache/manager.py) | JSON-кэш с TTL, клиент и адаптация async/sync-вызовов | Новое пространство ключей симуляции; полные записи не хранить в Redis |
| [Celery](../../../backend/service/infrastructure/messaging/celery_app.py), `celery_app`; [порты](../../../backend/service/infrastructure/messaging/ports.py) | Маршрутизация задач, очереди agents/maintenance, отмена, доступ к состоянию | Добавить очередь simulation и задачу backend; сохранить существующие очереди |
| [Репозиторий заданий](../../../backend/service/services/jobs/persistence/job_repository.py) | Записи заданий, блокировки строк и чатовые правила переходов | Общие транзакции использовать; чатовые резервирования и биллинг не переносить в симуляции |
| [WebSocket заданий](../../../backend/service/services/jobs/presentation/ws/jobs_ws.py); [Redis Streams](../../../backend/service/infrastructure/messaging/stream_helpers.py) | Аутентификация, поток, воспроизведение событий | Использовать транспортные примитивы с проверкой владельца и отдельной семантикой событий симуляции |
| [Выбор хранилища](../../../backend/service/composition/storage.py); [контракт](../../../backend/service/infrastructure/storage/abstract_file_storage.py) | Local/MinIO, потоковая загрузка и ограниченное чтение, идентичность хранилища | Один явно выбранный backend хранения; без автоматического переключения после ошибки |
| [Файловый сервис](../../../backend/service/services/files/application/file_saver_service.py), `save_stream`, `get_owned_download_url` | Владение, хеши, идемпотентная загрузка, восстановление регистрации | Сохранять файлы с типом SIMULATION; использовать существующие скачивания по ID |
| [SidecarClient](../../../backend/service/infrastructure/sidecar.py) | HTTP, correlation ID, потоковые ответы и классификация ошибок | Собственный клиент generator на той же основе; не импортировать соседние Python-пакеты |
| [Маршруты frontend](../../../frontend/src/app/router/routes.js), [ThreeStage](../../../frontend/src/three/ThreeStage.js), [общие controls](../../../frontend/src/shared/controls/) | React/Chakra, авторизация, ленивые страницы, Three.js, общие элементы | Страница симулятора и общий профиль; графики и сцена получают данные одного опыта |

## Текущие сайдкары

| Сайдкар | Реальная поверхность и основание | Повторное использование и граница |
|---|---|---|
| `agents` | [Контракт](../../../agents/service/contracts.py), [health](../../../agents/service/presentation/routers/health.py): `/run`, `/route`, шлюз моделей, инструменты и события | Помощь с протоколом и анализом. Авторизация и публикация файлов остаются в backend. LLM не создаёт численные трассы и эталонные метки |
| `duckdb` | [HTTP](../../../duckdb/service/app.py), [контракт](../../../duckdb/service/contracts.py), [ядро](../../../duckdb/service/core.py): `/query`, `/formats`, `/health`; отдельное соединение и временные файлы на запрос | Анализ ограниченных таблиц CSV/Parquet/JSON, агрегаты. Текущий транспорт передаёт файлы в теле запроса; крупные сигналы нельзя отправлять целиком без учёта его ограничений |
| `opendataloader` | [HTTP](../../../opendataloader/service/app.py), [контракт](../../../opendataloader/service/contracts.py): `/parse`, `/convert`, `/formats`, `/health`; JVM/LibreOffice для соответствующих форматов | Разбор методик и преобразование документов. Не нужен для расчёта сигналов. Health не доказывает успешную конверсию конкретного файла |
| `workspace` | [HTTP](../../../workspace/service/presentation/http.py), [контракты](../../../workspace/service/domain/contracts.py), [README](../../../workspace/README.md) | Файловая песочница, команды, история, IDE и сборка документов. Дополнительный анализ/отчёт; не место основного научного движка. Docker socket остаётся в существующей границе workspace, generator его не получает |
| `memos` | [Адаптер backend](../../../backend/service/infrastructure/memory/memos.py), [Compose](../../../memos/docker/docker-compose.yml) | Память помощника через HTTP; отдельные графовые/векторные данные. Не реестр опытов и не источник научной истины; включается по необходимости |
| `local_llm` | [HTTP](../../../local_llm/service/presentation/http.py), [конфигурация](../../../local_llm/service/configuration.py), [README](../../../local_llm/README.md) | CPU-инференс llama.cpp через проверяющий OpenAI-совместимый шлюз. Сохраняется для помощника; пригодность автономного tool-loop не считается доказанной и не является условием демо |
| `research` | [Архитектура](../../../research/docs/reference/architecture.md), [контракты](../../../research/service/interfaces/contracts.py) | Канонический JSON-реестр, CLI/MCP и read-only HTTP; производный гибридный поиск. Сохранять поколение/локаторы оснований; не смешивать с памятью MemOS и журналом запусков |
| `materials/text` | [README](../../../materials/text/README.md), [MCP](../../../materials/text/service/mcp_server.py), [manifest](../../../materials/text/sidecar.json) | Реестр и сборка диссертации, снимки доказательств, согласования. Включение результатов выполняется отдельной редакционной операцией |
| `materials/presentation` | [MCP](../../../materials/presentation/service/mcp_server.py), [manifest](../../../materials/presentation/sidecar.json) | Управляемая сборка презентаций; не средство непосредственного отображения симуляции |
| `materials/publications` | [MCP](../../../materials/publications/service/mcp_server.py), [manifest](../../../materials/publications/sidecar.json) | Рукописи/постеры и выпускные проверки; отчёт опыта не превращается автоматически в научную публикацию |
| `simulations/sidecars` | [Реестр 32 кандидатов](../../../simulations/data/registry.json), [REPORT](../../../simulations/REPORT.md) | Закреплённые внешние исходники, а не 32 готовых HTTP-сервиса. Для адаптера требуется отдельный допуск функций, версии данных, лицензии и единиц |

`backend` и `frontend` — приложения платформы; `infra` — конфигурации/данные инфраструктуры, а не самостоятельный вычислительный сайдкар. У перечисленных проектов разные транспорты и способы упаковки. Общий подход означает совместимые границы и проверки, а не принудительное превращение всех CLI/MCP в HTTP.

## Расхождения, которые надо учесть при интеграции

1. [NewJobProcessor](../../../backend/service/services/jobs/application/job_processor.py), `_process_job`: сохраняет состояние, но не запускает предметное вычисление. Не использовать как готовый исполнитель.
2. [ServiceType](../../../backend/service/models/key_value.py) содержит только CHAT. [JobService](../../../backend/service/services/jobs/application/job_service.py) включает чатовые правила и ограничение текущих заданий пользователя. Нужен отдельный доменный путь SIMULATION, а не подмена типа.
3. `build_infra` проверяет `CELERY_BROKER_URL`, а настройки Celery используют `CELERY__BROKER_URL`. Источник конфигурации должен стать единым с явной совместимостью старого имени.
4. [AuthContext](../../../frontend/src/features/auth/model/AuthContext.jsx), `resolveGuardRedirect`: `feature-flag` перенаправляет в чат; это не готовый режим симулятора. После входа тоже сейчас выбирается CHAT.
5. В jobs WebSocket исключение проверки владельца логируется при исходном `owned=True`. Перед повторным использованием доступ при ошибке БД должен закрываться. Общая consumer group также не доказывает полную доставку каждой вкладке; для симуляций нужен независимый курсор чтения.
6. Корневой `docker/` отсутствует, хотя Makefile и проверки ссылаются на него. Восстановленные приложения находятся вне текущих gitlink суперпроекта. Наличие `.git` внутри каталога не доказывает корректность будущего клонирования.
7. README DuckDB содержит прежний путь клиента; README opendataloader не полностью отражает `/convert` и текущие дедлайны. При реализации сверять контракт с кодом и исправлять затронутые инструкции.
8. `sidecar.json` у materials описывает документы и не является универсальным манифестом вычислительного сервиса. Новый manifest generator должен иметь собственную явную схему.

Ни одно из этих расхождений в текущем документальном проходе не исправлялось в коде.

Предметное переиспользование не ограничивается платформой: [отдельная карта SIM](10-simulation-reuse.md) сопоставляет источники сцены, геометрии, нейродинамики, механики и экспорта. Перед написанием каждого нового компонента требуется проверить эту карту и исходные результаты испытаний.
