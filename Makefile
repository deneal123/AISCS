# Makefile AISCS — команды стека и проверки конфигурации.
#
# Конфигураций ровно две: docker/docker-compose.dev.yaml (разработка, с GPU)
# и docker/docker-compose.yaml (прод, с GPU). Оба запускают генератор на
# видеокарте; отдельных оверлеев больше нет.

.PHONY: build run stop restart status logs shell
.PHONY: check-simulation-deployment simulation-status compose-check
.PHONY: test test-backend test-generator lint hooks
.PHONY: frontend-analyze create-user grant-admin revoke-admin

NO_CACHE ?= false
MODE ?= dev

ifeq ($(MODE),prod)
COMPOSE_FILE := docker/docker-compose.yaml
else
COMPOSE_FILE := docker/docker-compose.dev.yaml
endif

check-simulation-deployment:
	cd backend && uv run --frozen python -m pytest ../scripts/tests/test_deployment_contract.py -q -o addopts=''
	git diff --check

simulation-status: status

# Разбор обеих конфигураций с подстановкой переменных: единственная проверка,
# которая ловит и синтаксис compose, и забытый обязательный ключ.
compose-check:
	docker compose --env-file docker/.env.dev -p aspa-dev -f docker/docker-compose.dev.yaml --profile dev --profile celery config --quiet
	docker compose --env-file docker/.env.prod -p aspa-prod -f docker/docker-compose.yaml --profile prod --profile celery config --quiet
	@echo "compose: обе конфигурации разбираются"

build:
	@echo "Сборка образов ($(MODE)) через docker/build.sh; NoCache: $(NO_CACHE)"
	@test -x docker/build.sh || (echo "СТОП: docker/build.sh отсутствует или не исполним"; exit 2)
	@BUILD_OPTS=""; \
	  if [ "$(NO_CACHE)" = "true" ]; then BUILD_OPTS="$$BUILD_OPTS --no-cache"; fi; \
	  docker/build.sh --$(MODE) $$BUILD_OPTS

run:
	@echo "Запуск стека через docker/run.sh (--$(MODE))"
	@test -x docker/run.sh || (echo "СТОП: docker/run.sh отсутствует или не исполним"; exit 2)
	@docker/run.sh --$(MODE)

stop:
	@echo "Остановка стека через docker/run.sh --stop"
	@test -x docker/run.sh || (echo "СТОП: docker/run.sh отсутствует или не исполним"; exit 2)
	@docker/run.sh --$(MODE) --stop

restart:
	@docker/run.sh --$(MODE) --restart

status:
	@docker/run.sh --$(MODE) --status

logs:
	@docker/run.sh --$(MODE) --logs $(SERVICE)

# Оболочка в контейнере: make shell SERVICE=backend MODE=dev
shell:
	docker exec -it aspa-$(MODE)-$(SERVICE)-1 bash

test: test-backend
	@echo "Готово."

test-backend:
	cd backend && uv run --frozen pytest -q

# ⚠️ Тесты генератора гоняются ВНУТРИ образа, а не через `uv run` на хосте: его lockfile
# собран под linux (`environments = ["sys_platform == 'linux'"]`), и uv отказывается
# работать на Windows вообще. В образе есть uv и dev-группа, поэтому команда повторяет
# стадию test из generator/docker/Dockerfile.
#
# `UV_PROJECT_ENVIRONMENT` и `UV_CACHE_DIR` уведены в /tmp намеренно: по умолчанию
# `uv` создаёт `.venv` рядом с pyproject.toml, то есть в смонтированном каталоге
# репозитория — и после прогона в рабочем дереве остаётся 765 МБ чужих файлов
# (проверено: ровно так и случилось при первом запуске).
# ⚠️ Пути внутри контейнера пишутся с ДВОЙНЫМ слэшем (`//src`, `//tmp/...`). Рецепты make
# на этой машине исполняет Git Bash, а он преобразует одиночный `/src` в windows-путь
# `C:/Program Files/Git/src` и docker падает с «working directory is invalid». Двойной
# слэш MSYS оставляет как есть.
GENERATOR_IMAGE ?= aspa-generator-gpu:20261115
test-generator:
	docker run --rm -v "$(CURDIR)/generator://src" -w //src \
	  -e UV_PROJECT_ENVIRONMENT=//tmp/venv -e UV_CACHE_DIR=//tmp/uv-cache \
	  $(GENERATOR_IMAGE) sh -lc "cd //src && uv run --frozen --group dev python -m pytest -q $(PYTEST_ARGS)"

lint:
	@echo "Running pre-commit hooks..."
	pre-commit run --all-files

hooks:
	@echo "Installing pre-commit hooks (superproject + submodules)..."
	pre-commit install
	@for m in backend generator frontend; do \
	  if [ -f "$$m/.pre-commit-config.yaml" ]; then \
	    (cd "$$m" && pre-commit install >/dev/null && echo "  $$m: установлено"); \
	  else \
	    echo "  $$m: конфига нет — пропуск"; \
	  fi; \
	done

frontend-analyze:
	@echo "Run frontend bundle analysis (source-map-explorer)..."
	cd frontend && npm run build:analyze

# Пользователь для разработки с подтверждённым email: /login работает без OTP.
#   make create-user EMAIL=dev@example.com PASSWORD=devpass123
create-user:
	@if [ -z "$(EMAIL)" ] || [ -z "$(PASSWORD)" ]; then \
	  echo "Usage: make create-user EMAIL=you@example.com PASSWORD=secret123 [MODE=dev|prod]"; exit 2; fi
	@docker exec -i aspa-$(MODE)-backend-1 python - "$(EMAIL)" "$(PASSWORD)" \
	  < backend/scripts/create_dev_user.py

grant-admin:
	@if [ -z "$(EMAIL)" ]; then echo "Usage: make grant-admin EMAIL=user@example.com [MODE=dev|prod]"; exit 2; fi
	@echo "Promoting $(EMAIL) to admin (mode=$(MODE))..."
	@out=$$(docker exec aspa-$(MODE)-postgres-1 sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "UPDATE profile.\\"user\\" SET is_admin = true WHERE lower(email) = lower('"'"'$(EMAIL)'"'"');"' 2>&1); \
	 echo "$$out" | grep -q "UPDATE 1" \
	   && echo "OK: $(EMAIL) is now an administrator (re-login to refresh the session)." \
	   || { echo "FAILED: no account with email $(EMAIL) — nothing changed."; echo "$$out"; exit 1; }

revoke-admin:
	@if [ -z "$(EMAIL)" ]; then echo "Usage: make revoke-admin EMAIL=user@example.com [MODE=dev|prod]"; exit 2; fi
	@echo "Revoking admin from $(EMAIL) (mode=$(MODE))..."
	@out=$$(docker exec aspa-$(MODE)-postgres-1 sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "UPDATE profile.\\"user\\" SET is_admin = false WHERE lower(email) = lower('"'"'$(EMAIL)'"'"');"' 2>&1); \
	 echo "$$out" | grep -q "UPDATE 1" \
	   && echo "OK: $(EMAIL) is no longer an administrator." \
	   || { echo "FAILED: no account with email $(EMAIL) — nothing changed."; echo "$$out"; exit 1; }
