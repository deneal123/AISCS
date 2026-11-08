# Инфраструктура AISCS

Исходные dev/prod определения и build/run перенесены из GPTHub. Профиль `simulation`
расширяет выбранные сервисы; исходные определения сохранены. Источники переноса,
границы проверки и план research: [решение 12](../docs/Материалы/План_генератора_2026-10/12-platform-infrastructure.md).

```sh
bash docker/build.sh --dev
bash docker/run.sh --dev
bash docker/run.sh --dev --status
bash docker/run.sh --dev --logs backend
bash docker/run.sh --dev --stop
```

Скопированные `.env.dev` и `.env.prod` приватны и игнорируются Git. Не выводить
`docker compose config` или `config --environment` в терминал: там секреты.
Использовать `config --quiet`. Общий sync_env создаёт отсутствующие внутренние
ключи, сохраняя рабочие. `PYTHON_BIN` позволяет указать Python в Git Bash.

Локальные адреса: frontend `http://localhost:8095`, backend `http://localhost:8094`,
Mailpit `http://localhost:8027`. PostgreSQL и MinIO публикуются только на loopback.
Beat, maintenance и simulation — отдельные процессы; broker — Redis.
Переменная backend `SIMULATION_QUEUE` при необходимости отделяет очередь испытаний;
по умолчанию используется `simulation`. При изменении имени воркер необходимо
запускать с соответствующим `--queues`, иначе задания останутся в очереди.

Дополнительный `docker-compose.simulation.gpu.yaml` подготовлен для GPU-расчёта
поля после завершения полного кэша. Он выбирает `gpu-runtime`, передаёт GPU,
монтирует кэш только для чтения и требует явно заданные
`GENERATOR_GEOMETRY_CACHE_HOST_PATH` и `GENERATOR_GEOMETRY_CACHE_MANIFEST_SHA256`.
Хеш нужно сохранить из вывода успешного построения отдельно от каталога кэша;
индекс и аудит используются из уже настроенного `/morphology-index`. Настройки
сами по себе ничего не запускают. GPU-образ, подключение контейнера и полный
расчёт по этому файлу ещё не проверены; это не ускорение NEURON или всей сети.
Для экспериментального пакетного оператора администратор может явно задать
`GENERATOR_FIELD_BACKEND=gpu-fused`; без этой настройки сохраняется `gpu`.
Полный кэш и отдельно сохранённый хеш обязательны. Это не проверка развёртывания.

В dev-профиле исходная морфология MaleCNS монтируется в generator только для
чтения из двух каталогов в `.data/male-cns/`. При переносе
данных можно задать `GENERATOR_MORPHOLOGY_EXISTING_PATH` и
`GENERATOR_MORPHOLOGY_FULL_PATH` в приватном `.env.dev`: каждый каталог содержит
`raw/<body_id>.swc` и `receipts/<body_id>.json`. Один только SWC без проверенной
квитанции сервис не публикует. Монтирование выполняется при пересоздании
контейнера; эти научные данные и квитанции не включаются в Git или образ.
Постоянный каталог `.data/` игнорируется Git; временную `.work/` не следует
считать архивом данных. Полнота и хеши проверены перед переносом; после переноса
проверено подключение обоих каталогов и чтение отдельных нейронов.

Для пространственного поиска dev-профиль монтирует только для чтения
`.data/male-cns/morphology-index/`: `verified-bounds-v2.sqlite` и
`verified-bounds-v2.audit.json`. Переносить индекс следует вместе с квитанцией
независимого аудита и проверять SHA-256 по полю `index_sha256`; исходные SWC и
их квитанции также должны соответствовать проверенному снимку. Путь каталога
задаётся `GENERATOR_MORPHOLOGY_INDEX_PATH`, число процессов поиска —
`GENERATOR_MORPHOLOGY_SPATIAL_WORKERS` (по умолчанию 4, допустимо 1–8).
Один процесс сервиса допускает только один одновременный поиск; остальные
получают 429. При отсутствии или повреждении индекса сервис отказывает в
поиске, не выдавая частичный результат за полный. Близость отростка к контакту
не доказывает возбуждение. Новый образ и монтирование вступают в силу только
после сборки и пересоздания generator; действующий процесс автоматически не обновляется.

MinIO локального профиля собирается из проверяемого архива закреплённого upstream
commit; исторический образ из публичного реестра для запуска не требуется.
Build context содержит только [файлы сборки MinIO](minio/README.md).
Это наша сборка исходников, не копия digest исторического образа.

Проверки отказов выполняются в отдельном Compose project с пустыми томами:

```sh
docker compose --env-file docker/.env.dev -p aspa-acceptance-safety \
  -f docker/docker-compose.simulation.yaml \
  -f docker/docker-compose.simulation.acceptance.yaml \
  -f docker/docker-compose.simulation.acceptance-faults.yaml \
  --profile dev --profile celery up -d --wait
python scripts/simulation_safety_acceptance.py --project aspa-acceptance-safety
```

Сценарий требует Python-окружения backend и `websockets`; его журнал и отчёт идут
в игнорируемую `.work`. Test-only прокси и управление отказами доступны только
в этом overlay. Никогда не применять его к `aspa-dev` или production.
После проверки удалить только собственный acceptance project командой `down --volumes`
с теми же `-p` и `-f`; результаты тестов при этом сохраняются вне Docker-томов.

Production подготовлен для `https://aiscs.incellcorp.ru` и S3 `aiscs`; не запущен.
Заполнить `MINIO__ACCESS_KEY` / `MINIO__SECRET_KEY` в `.env.prod`, установить AISCS
сертификат в `infra/nginx/certs/aiscs/` и настроить внешний Nginx. Проверить
`prod.env.example`; API/WS frontend остаются same-origin. До приёмки сервера не
считать конфигурацию работающим production. Штатные `--prod` используют отдельный
Compose, тома и namespace `aspa-prod`.

Research пока запускается отдельно и сохраняет свой Docker project и тома.
Включение в общую команду и страница поиска запланированы, исходники research
этим изменением не затрагиваются.
