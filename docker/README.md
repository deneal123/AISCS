# Docker-контуры research

Все команды выполняются из корня research. Контекст сборки — этот же корень; конфигурации находятся здесь, в `docker/`.

| Файл | Назначение |
|---|---|
| [Dockerfile](Dockerfile), [entrypoint.sh](entrypoint.sh) | Непривилегированный HTTP/CLI runtime; зависимости из `uv.lock` |
| [compose.yaml](compose.yaml) | Самостоятельный HTTP-реестр, порт 8091 на loopback |
| [compose.knowledge.yaml](compose.knowledge.yaml) | Отдельные Neo4j, Qdrant, шлюз и сервис knowledge |
| [../.dockerignore](../.dockerignore) | Разрешённый состав контекста сборки |

## Обычный реестр

```powershell
docker compose -f docker/compose.yaml config --quiet
docker compose -f docker/compose.yaml up -d --build --wait
docker compose -f docker/compose.yaml down
```

Имя Compose-проекта `research` сохранено явно после переноса файла. Для проверки образа без запуска постоянного сервиса: `make docker-smoke`. HTTP остаётся только для чтения; изменять канон следует через локальный curation pipeline.

## Графовый и векторный поиск

Нужны зарегистрированные тексты/состояние `.knowledge/`, собственные тома графа и векторов, действующий шлюз embeddings и закрытый `.knowledge/runtime.env`. Образец ключей — в [../.env.example](../.env.example); секреты в репозиторий не добавляются.

В конфигурации по умолчанию checkout шлюза ожидается в соседнем `agents/`, сертификат — в `infra/certs/` суперпроекта. Если их там нет, задать `RESEARCH_AGENTS_DIR` и `RESEARCH_GIGACHAT_CA_FILE` абсолютными путями в закрытом env-файле. Относительные пути Compose разрешаются от `research/docker/`, а путь после `--env-file` — от текущего рабочего каталога. Не подставлять произвольный checkout вместо совместимой версии шлюза.

```powershell
docker compose --env-file .knowledge/runtime.env -f docker/compose.knowledge.yaml --profile knowledge up -d --build --wait
docker compose --env-file .knowledge/runtime.env -f docker/compose.knowledge.yaml --profile knowledge ps
docker compose --env-file .knowledge/runtime.env -f docker/compose.knowledge.yaml --profile knowledge down
```

Имя проекта `aspa-research-knowledge`, сеть и имена томов сохранены. `down` без `-v` сохраняет данные; общий prune томов не является уборкой кэша. Перенос конфигурации не перестраивает и не публикует поколение индекса. Проверка доступности шлюза и реального hybrid-поиска описана в [knowledge](../knowledge/README.md).

Bind-mounts не создают отсутствующие пути автоматически: неверный путь сертификата или канона должен завершить запуск ошибкой, а не оставить пустой каталог вместо файла.

## Контекст и очистка

Образ получает только runtime, зафиксированные зависимости, зарегистрированные данные и knowledge-схемы. Docker не получает `.git`, `.env`, `.work`, `.knowledge`, локальные окружения, tests и кэши. Канонические базовые архивы входят в образ, поскольку валидация использует их; полные тексты и Docker-тома туда не копируются.

После временных испытаний удалять только созданные для них контейнеры и образы. Не останавливать чужие службы и не выполнять общую очистку Docker на машине с другими проектами.
