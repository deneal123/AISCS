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
