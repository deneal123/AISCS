# Инфраструктура AISCS

В проекте РОВНО ДВЕ конфигурации, как в gpthub: `docker-compose.dev.yaml` и
`docker-compose.yaml`. Отдельных оверлеев (simulation, gpu, acceptance, local-llm)
больше нет — GPU-настройки симулятора живут прямо в этих двух файлах.

| файл | проект | назначение |
| --- | --- | --- |
| `docker-compose.dev.yaml` | `aspa-dev` | разработка: фронт с live-reload, API с монтированным кодом, Postgres, Redis, MinIO, Mailpit и генератор на GPU |
| `docker-compose.yaml` | `aspa-prod` | прод: собранный фронт за nginx, без MinIO (внешнее S3), без Mailpit |

Оба поднимают генератор (он же симулятор ЦНС) на видеокарте: `build.target: gpu-runtime`,
`gpus: all`, `GENERATOR_FIELD_BACKEND=gpu` и обязательный кэш геометрии.

## Запуск

```sh
bash docker/build.sh --dev      # или: make build MODE=dev
bash docker/run.sh --dev        # или: make run MODE=dev
bash docker/run.sh --dev --status
bash docker/run.sh --dev --logs backend
bash docker/run.sh --dev --stop
```

Разбор обеих конфигураций с подстановкой переменных — `make compose-check`.
Скрипты требуют bash (на Windows подходит Git Bash), поэтому `make` вызывает их
через свой шелл; отдельного «make-варианта» сборки нет, чтобы правила были одни.

Адреса dev: frontend `http://localhost:8095`, backend `http://localhost:8094`,
MinIO `http://localhost:9091`, Mailpit `http://localhost:8027`,
PostgreSQL `127.0.0.1:5546`. Порты задаются в `docker/.env.dev`
(`FRONTEND_PORT`, `BACKEND_PORT`, `MINIO_PORT`, `MINIO_CONSOLE_PORT`,
`MAILPIT_PORT`, `POSTGRES_HOST_PORT`).

Сервисы: `frontend`, `backend`, `postgres`, `redis`, `minio` (только dev),
`mailpit` (только dev), `generator`, `celery-worker-maintenance`,
`celery-worker-simulation`, `celery-beat`, `nginx` (только prod).
Сайдкары workspace, duckdb, opendataloader, memos, local_llm, agents, whisper,
video, graphify, ldr и searxng удалены из проекта и из стека.

## Переменные окружения

Три файла в `docker/`: `.env.example` (шаблон, отслеживается Git), `.env.dev` и
`.env.prod` (приватные, `.gitignore`). Все три содержат ОДИН И ТОТ ЖЕ набор из
125 ключей в одном порядке — так различие между конфигурациями видно построчно.
Порядок секций: Docker/сборка, хостовые порты, nginx (прод), API-сервис,
аутентификация, CORS, хранилище, базы и очереди, почта, ручки IDE, генератор,
биллинг, платежи, админ, уведомления.

Контракт проверяется `scripts/check_env_contract.py` (хук `env-contract`):
ключи шаблона обязаны быть в обеих конфигурациях, а переменные, которые реально
читает код backend и generator, — объявлены в шаблоне. Заодно ловится расхождение
имён: например, код читает `GENERATOR_MORPHOLOGY_RADIUS_DB`, а compose одно время
подставлял `GENERATOR_RADIUS_DB` — проверка контактов падала бы всегда.

⚠️ Не выводить `docker compose config` без `--quiet`: в подстановке видны секреты.

## Генератор и GPU

Кэш геометрии обязателен: без него batch-путь отвергает GPU-конфигурацию
(`_field_geometry_cache` в `service/infrastructure/execution/process.py`).
Compose монтирует каталог кэша только для чтения и передаёт его манифест:

- `GENERATOR_GEOMETRY_CACHE_DIR=/geometry-cache`
- `GENERATOR_GEOMETRY_CACHE_MANIFEST_SHA256` — по умолчанию
  `bf6374d275de2c52b908fa1b7847d3f7a97be401adc70e9a6ad0ca658ab0a725`
- `GENERATOR_GEOMETRY_SOURCE_INDEX=/morphology-index/verified-bounds-v2.sqlite`
- `GENERATOR_GEOMETRY_SOURCE_AUDIT=/morphology-index/verified-bounds-v2.audit.json`

Хост-путь кэша — `GENERATOR_GEOMETRY_CACHE_HOST_PATH`, по умолчанию
`.data/male-cns/geometry-cache-v1-zlib`. Если кэш пересобран, хеш нужно взять из
его `manifest.json` (поле `manifest_sha256` в квитанции) и положить в
`.env.dev`; устаревший хеш даёт отказ ещё до старта расчёта.

Экспериментальный batch-оператор включается явно:
`GENERATOR_FIELD_BACKEND=gpu-fused`. По умолчанию стоит `gpu`.

## Научные данные (только чтение)

Морфология MaleCNS монтируется в генератор из `.data/male-cns/`:

- `morphology/` и `full-morphology/` — `raw/<body_id>.swc` + `receipts/<body_id>.json`;
  один SWC без проверенной квитанции сервис не публикует;
- `morphology-index/` — `verified-bounds-v2.sqlite` + `.audit.json`,
  `verified-radii-v1.sqlite`, `verified-segments-v1.sqlite` (с такими же аудитами);
- `overview-v1/`, `synapses/`, `source-pairs-v2/`, `neuropil-lod-v1/` — только чтение;
- `source-diagnostics/` — единственный каталог с записью (кеш диагностики источников).

Пути переопределяются ключами `GENERATOR_*_PATH` в `.env.dev`. Каталог `.data/`
игнорируется Git; `.work/` — временный, архивом данных не является.

Пространственный поиск: `GENERATOR_MORPHOLOGY_SPATIAL_WORKERS` (по умолчанию 4,
допустимо 1–8). Один процесс сервиса допускает один одновременный поиск,
остальные получают 429. При отсутствии или повреждении индекса сервис отказывает
в поиске, не выдавая частичный результат за полный.

MinIO dev-профиля собирается из закреплённого архива
([minio/README.md](minio/README.md)); исторический образ из публичного реестра для
запуска не требуется.

## Прод

Подготовлен для `https://aiscs.incellcorp.ru` и S3 `aiscs`, не запущен.
Перед запуском: заполнить `MINIO__ACCESS_KEY` / `MINIO__SECRET_KEY` в `.env.prod`,
положить сертификат в `infra/nginx/certs/certificate.pem` и ключ в
`infra/nginx/certs/private.pem` (это же проверяет `production_preflight`),
настроить внешний nginx. API и WS фронтенда остаются same-origin: бандл собирается
без `REACT_APP_*_BASE_URL`, а nginx проксирует `/api` и `/ws`.
В прод-конфигурации `REACT_APP_APPLICATION_PROFILE=simulation` передаётся как
build-arg — иначе в бандл попадал бы дефолт `gpthub` из Dockerfile.

## Тесты

- Контракт развёртывания и env: `make check-simulation-deployment` или
  `uv run --no-project --with pytest --with PyYAML python -m pytest scripts/tests/test_deployment_contract.py scripts/tests/test_env_file_drift.py`.
- Генератор (в образе, потому что его lockfile собран под linux):
  `make test-generator` (по умолчанию весь набор, `PYTEST_ARGS=...` сужает).
- Backend: `make test-backend`.
- Все хуки: `pre-commit run --all-files`.
