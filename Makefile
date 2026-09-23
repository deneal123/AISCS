# Makefile GPTHub — обёртка над docker compose и проверками суперпроекта.

# ⚠️ Цели перечислять здесь ОБЯЗАТЕЛЬНО: без .PHONY цель молча не выполнится,
# если в корне появится одноимённый файл. Раньше не были объявлены stop, graph
# и create-user.
.PHONY: build test lint run stop graph hooks
.PHONY: frontend-analyze create-user grant-admin revoke-admin
.PHONY: test-cross-service smoke-agents smoke-gigachat-tools smoke-gigachat-workspace smoke-gigachat-qualification
.PHONY: test-run-quality-gate test-s26-quality-gate test-s27-ui-gate test-s28-workbench-gate
.PHONY: test-s29-capability-gate test-s30-ledger-gate test-s31-provider-gate test-s32-provider-admission-gate
.PHONY: test-s33-provider-generation-gate test-s34-document-gate test-s35-document-authoring-gate smoke-document-runtime
.PHONY: test-s36-document-gate recreate-s36-document-stack smoke-s36-document-live smoke-s36-pdf-agent

# ⚠️ ОТСЮДА УБРАНЫ DOCKERHUB_REPO / TAG / IMAGE / DOCKER_BUILD_ARGS /
# BUILD_CONTEXT_BACKEND. Это был второй, НИКОГДА НЕ ИСПОЛНЯВШИЙСЯ путь сборки:
# цель `build` делегирует в docker/build.sh (он есть и исполним всегда), а ветка
# `else` с прямым `docker build -t $(IMAGE)` не выполнялась ни разу. Единственным
# следом была строка «Building backend image mydockerhubuser:latest» — она
# печаталась при КАЖДОЙ сборке и называла образ, который не собирается.
# Публикации в реестр в проекте нет ни в каком виде: заводить её надо осознанно,
# а не восстанавливать мёртвое.
NO_CACHE ?= false
MODE ?= dev
GIGACHAT_SMOKE_MODEL ?= GigaChat-3-Lightning
# Опциональные тяжёлые стеки. Пример: make run MEMOS=1 LDR=1
# (сабмодули MemOS/local-deep-research должны быть инициализированы).
MEMOS ?= 0
LDR ?= 0

build:
	@echo "Сборка образов ($(MODE)) через docker/build.sh; NoCache: $(NO_CACHE)"
	@test -x docker/build.sh || (echo "СТОП: docker/build.sh отсутствует или не исполним"; exit 2)
	@BUILD_OPTS=""; \
	  if [ "$(NO_CACHE)" = "true" ]; then BUILD_OPTS="$$BUILD_OPTS --no-cache"; fi; \
	  MEMOS=$(MEMOS) LDR=$(LDR) docker/build.sh --$(MODE) $$BUILD_OPTS

# Backend-половина бывших кросс-сервисных тестов (агентская живёт в agents/tests/
# cross_service и гоняется прогоном сайдкара).
#
# ⚠️ ОТСЮДА УБРАН `PYTHONPATH=…/agents`. Он подкладывал домен агентов, когда тот
# был отдельным пакетом `gpthub_agents`. После переименования пакета сайдкара в
# `service` эта строка стала ВРЕДНОЙ: у backend свой верхний пакет с тем же именем,
# и два разных `service` в одном интерпретаторе не уживаются — ровно та коллизия,
# из-за которой тесты и разделили (см. backend/tests/cross_service/conftest.py).
# Зависимости от домена здесь не осталось ни в одном тесте, подкладывать нечего.
#
# ⚠️ `uv run --frozen`, а не голый `python -m pytest`: голое имя берётся из PATH,
# где оказывается венв первого попавшегося соседнего сервиса.
test-cross-service:
	@echo "Running cross-service tests (backend-половина)..."
	cd backend && uv run --frozen pytest tests/cross_service -q --no-cov

# Детерминированный merge-gate S16. Сначала сверяем две независимые тестовые
# декларации (agents/backend нельзя импортировать одним Python-процессом), затем
# запускаем только сценарии, образующие сквозной контракт. В fixtures нет реальных
# запросов, аргументов или результатов инструментов.
test-run-quality-gate:
	uv run --project agents --frozen python scripts/check_protocol_manifest.py
	uv run --project agents --frozen python scripts/check_privacy_boundaries.py
	uv run --project agents --frozen python scripts/check_gigachat_ca.py
	cd agents && uv run --frozen python ../scripts/check_run_quality_gate.py
	cd agents && uv run --frozen pytest -q tests/test_full_run_golden.py tests/test_tool_loop_golden.py tests/test_tool_disclosure.py tests/test_auto_mode_integration.py tests/test_workflow_catalog.py tests/test_mcp_transport.py tests/test_app.py tests/test_run_deadline.py tests/test_gigachat_schema.py tests/test_gigachat_streaming.py
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_http_agent_engine.py tests/test_chat_stream_consumer.py

# Full offline S26 release gate. Network/provider acceptance is intentionally
# separate: this target must be deterministic and runnable without production
# prompts, credentials or a live sidecar.
test-s26-quality-gate: test-run-quality-gate
	uv run --project agents --frozen python scripts/check_contract_parity.py
	uv run --project agents --frozen python scripts/check_shared_copies.py
	cd agents && uv run --frozen ruff check .
	cd agents && uv run --frozen ruff format --check .
	cd agents && uv run --frozen python scripts/check_module_complexity.py
	cd agents && uv run --frozen pytest -q
	cd backend && uv run --frozen ruff check .
	cd backend && uv run --frozen ruff format --check .
	cd backend && uv run --frozen mypy service
	cd backend && uv run --frozen python scripts/check_module_complexity.py
	cd backend && uv run --frozen pytest -q
	cd workspace && uv run --frozen ruff check .
	cd workspace && uv run --frozen ruff format --check .
	cd workspace && uv run --frozen pytest -q
	cd frontend && npm test -- --runInBand
	cd frontend && npm run lint
	cd frontend && npm run build
	cd frontend && npx playwright test tests/e2e/work-hub.spec.js --config=tests/e2e/playwright.config.js --project=chromium --project=mobile-chrome
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery --profile memos --profile ldr config -q
	GPTHUB_WORKSPACE_COORDINATION_SECRET=s26-compose-validation-only docker compose --env-file docker/.env.prod -f docker/docker-compose.yaml --profile prod --profile celery --profile memos --profile ldr config -q
	git diff --check

# S27 Workbench UI gate. It is intentionally deterministic and serves the
# already-built frontend with the local SPA test server; the live Compose flow
# remains a separate acceptance check because it needs an isolated dev user.
test-s27-ui-gate:
	cd frontend && npm run verify:premium
	cd frontend && npm test -- --runInBand
	cd frontend && npm run lint
	cd frontend && npm run build
	cd frontend && npm run test:a11y
	cd frontend && npm run test:e2e:work
	git diff --check

# S28 continuity gate: the same deterministic premium/a11y/browser contract,
# extended by dirty-navigation, issue lifecycle and Library preservation tests.
test-s28-workbench-gate:
	cd frontend && npm run verify:premium
	cd frontend && npm test -- --runInBand
	cd frontend && npm run lint
	cd frontend && npm run build
	cd frontend && npm run test:a11y
	cd frontend && npm run test:e2e:work
	git diff --check

# S29 fail-fast capability graph. Provider/network acceptance stays outside this
# deterministic gate; Compose parsing and the image-build preflight cover startup.
test-s29-capability-gate:
	uv run --project agents --frozen python scripts/check_capability_manifest.py
	uv run --project agents --frozen python scripts/check_contract_parity.py
	cd agents && uv run --frozen pytest -q
	cd agents && uv run --frozen ruff check .
	cd agents && uv run --frozen ruff format --check .
	cd agents && uv run --frozen python scripts/check_module_complexity.py
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery --profile memos --profile ldr config -q
	git diff --check

# S30 closes the run-scoped accounting contract. The static tests forbid mutable
# usage accumulators and detached execution contexts in production; the full agents
# suite and existing paired transport corpus protect the unchanged wire/billing seam.
test-s30-ledger-gate: test-run-quality-gate
	uv run --project agents --frozen python scripts/check_capability_manifest.py
	uv run --project agents --frozen python scripts/check_contract_parity.py
	cd agents && uv run --frozen pytest -q tests/test_s30_execution_context.py tests/test_s30_static_gate.py tests/test_usage_out_static_gate.py
	cd agents && uv run --frozen pytest -q
	cd agents && uv run --frozen ruff check .
	cd agents && uv run --frozen ruff format --check .
	cd agents && uv run --frozen python scripts/check_module_complexity.py
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_http_agent_engine.py tests/test_chat_stream_consumer.py tests/cross_service
	git diff --check

# S31 makes a successful provider inventory authoritative and keeps fallback
# capabilities explicit. Live qualification remains an opt-in acceptance target.
test-s31-provider-gate: test-s30-ledger-gate
	uv run --project agents --frozen python scripts/check_protocol_manifest.py
	cd agents && uv run --frozen pytest -q tests/test_s31_provider_catalog.py tests/test_model_requirements.py tests/test_provider_resilience.py tests/test_provider_health_computes.py tests/test_protocol_manifest.py
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_protocol_manifest.py
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery --profile memos --profile ldr config -q
	git diff --check

# S32 freezes provider catalogs, evidence and clients for the lifetime of one
# run. Health/key rotation may refresh process state, but only the next run sees it.
test-s32-provider-admission-gate: test-s31-provider-gate
	uv run --project agents --frozen python scripts/check_protocol_manifest.py
	cd agents && uv run --frozen pytest -q tests/test_s32_provider_admission.py tests/test_s31_provider_catalog.py tests/test_provider_resilience.py tests/test_provider_health_computes.py tests/test_protocol_manifest.py
	cd agents && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd agents && uv run --frozen python scripts/check_module_complexity.py
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_protocol_manifest.py tests/test_http_agent_engine.py tests/test_chat_stream_consumer.py
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery --profile memos --profile ldr config -q
	git diff --check

# S33 binds every model operation to one immutable provider/client generation.
# The focused corpus covers draining, operation evidence, schema compilation and
# embedding dimensions; the inherited S32 gate protects run-level invariants.
test-s33-provider-generation-gate: test-s32-provider-admission-gate
	uv run --project agents --frozen python scripts/check_protocol_manifest.py
	cd agents && uv run --frozen pytest -q tests/test_s33_provider_generation.py tests/test_s33_provider_operation_boundaries.py tests/test_s32_provider_admission.py tests/test_provider_health_computes.py tests/test_protocol_manifest.py
	cd agents && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd agents && uv run --frozen python scripts/check_module_complexity.py
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_protocol_manifest.py tests/test_http_agent_engine.py tests/test_chat_stream_consumer.py
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery --profile memos --profile ldr config -q
	git diff --check

# S34 compiles trusted LaTeX profiles into the immutable capability graph and
# verifies the workspace/compiler/backend/Work Hub seams without network access.
# Building the large TeX runtime image remains an explicit live acceptance step.
test-s34-document-gate: test-s33-provider-generation-gate
	uv run --project agents --frozen python scripts/check_document_profiles.py
	cd workspace && uv run --frozen pytest -q
	cd workspace && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd agents && uv run --frozen pytest -q tests/test_document_forge.py tests/test_capability_compiler.py tests/test_gigachat_schema.py
	cd agents && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_document_forge_artifacts.py tests/test_work_hub_intake.py tests/test_artifact_surcharge_requires_artifact.py
	cd backend && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd frontend && npm test -- --runInBand
	cd frontend && npm run lint && npm run build && npm run verify:premium
	cd frontend && npx playwright test tests/e2e/work-hub.spec.js --config=tests/e2e/playwright.config.js --project=chromium --grep "vendor kit"
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery config -q
	git diff --check

# S35 proves typed semantic authoring, evidence-only citations, atomic source
# publication, effective vendor profiles, bounded repair and durable audit billing.
test-s35-document-authoring-gate: test-s34-document-gate smoke-document-runtime
	uv run --project agents --frozen python scripts/check_document_profiles.py
	cd agents && uv run --frozen pytest -q
	cd agents && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd agents && uv run --frozen python scripts/check_module_complexity.py
	cd workspace && uv run --frozen pytest -q tests/test_document_authoring_state.py tests/test_document_source_service.py tests/test_document_vendor_overlays.py tests/test_document_vendor_profiles.py tests/test_document_runner_policy.py tests/test_document_build_manager.py
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_document_forge_artifacts.py tests/test_document_publication_audit_billing.py
	cd backend && uv run --frozen mypy service
	cd frontend && npm test -- --runInBand tests/unit/components/DocumentForgePanel.test.jsx tests/unit/features/workspace-room/useDocumentForge.test.js
	cd frontend && npm run lint && npm run build && npm run verify:premium
	git diff --check

# S36 proves attachment evidence, one shared protocol repair, resumable section
# checkpoints, opaque confirmation anchors and honest document terminal states.
test-s36-document-gate: test-s35-document-authoring-gate
	uv run --project agents --frozen python scripts/check_document_runtime_freshness.py
	cd agents && uv run --frozen pytest -q tests/test_s36_document_authoring.py tests/test_s35_document_authoring.py tests/test_document_forge.py
	cd agents && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd workspace && uv run --frozen pytest -q tests/test_document_authoring_checkpoints.py tests/test_document_authoring_state.py tests/test_document_source_service.py tests/test_document_build_manager.py
	cd workspace && uv run --frozen ruff check . && uv run --frozen ruff format --check .
	cd backend && uv run --frozen pytest -q -o addopts='' tests/test_s36_confirmation_and_attachments.py tests/test_reservation_overspend_gate.py tests/test_mode_offer_expires_on_server.py tests/test_attachment_survives_reload.py tests/test_document_forge_artifacts.py tests/test_document_publication_audit_billing.py
	cd backend && uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen mypy service
	cd frontend && npm test -- --runInBand tests/unit/components/ModeOffer.test.jsx tests/unit/components/ChatDocumentRecoveryActions.test.jsx tests/unit/features/chat/offerAcceptance.test.js tests/unit/features/chat/useChatMessageSender.confirmation.test.js tests/unit/features/chat/useMessageActions.documentRetry.test.js tests/unit/features/chat/modelSelector.test.js tests/unit/features/chat/documentStatus.test.js tests/unit/features/chat/useChatStreamingLifecycle.test.js tests/unit/features/chat/useWebSocketChat.protocol.test.js
	cd frontend && npm run lint && npm run build
	git diff --check

recreate-s36-document-stack:
	$(MAKE) smoke-document-runtime
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery build agents workspace backend celery-worker-agents
	docker compose --env-file docker/.env.dev -f docker/docker-compose.dev.yaml --profile dev --profile celery up -d --force-recreate --wait --wait-timeout 180 agents workspace backend celery-worker-agents

smoke-s36-document-live: recreate-s36-document-stack
	uv run --project agents --frozen python scripts/check_document_runtime_freshness.py --live
	$(MAKE) smoke-s36-pdf-agent

smoke-s36-pdf-agent:
	@payload=$$(mktemp); \
	  cleanup() { \
	    if [ -s "$$payload" ]; then \
	      cat "$$payload" | docker exec -i gpthub-$(MODE)-backend-1 \
	        python -m service.utils.gigachat_workspace_fixture cleanup >/dev/null; \
	    fi; \
	    rm -f "$$payload"; \
	  }; \
	  trap cleanup EXIT INT TERM; \
	  docker exec gpthub-$(MODE)-backend-1 \
	    python -m service.utils.gigachat_workspace_fixture provision > "$$payload"; \
	  cat "$$payload" | docker exec -i -e GIGACHAT_SMOKE_MODEL=$(GIGACHAT_SMOKE_MODEL) \
	    -e S36_SMOKE_CASE=$(S36_SMOKE_CASE) \
	    gpthub-$(MODE)-agents-1 \
	    python -m service.presentation.cli.document_authoring_smoke

smoke-document-runtime:
	docker build -t gpthub-document-runtime:latest -f workspace/docker/document-runtime.Dockerfile workspace
	uv run --project agents --frozen python scripts/smoke_document_runtime.py --all-profiles

# Смоук сайдкара ПОСЛЕ выкладки. Хелсчек compose намеренно мягкий (curl -f /health):
# он отдаёт 200 даже когда движок не загрузился — иначе получили бы рестарт-петлю и
# потеряли ту самую диагностику, ради которой /health и существует. Значит утверждение
# «сервис работоспособен» надо делать ОТДЕЛЬНО, вот здесь: контейнер может быть healthy,
# а /run отвечать 503, /route — обваливать роутинг, /v1 — молча ронять memos/ldr.
#   make smoke-agents            # dev
#   make smoke-agents MODE=prod
smoke-agents:
	@docker exec gpthub-$(MODE)-backend-1 python -c "\
import json, sys, urllib.request; \
d = json.load(urllib.request.urlopen('http://agents:8090/health', timeout=15)); \
bad = [k for k in ('engine', 'gateway_v1', 'routing') if not d.get(k, {}).get('available')]; \
print('agents smoke:', 'OK' if not bad else 'НЕ ГОТОВ: ' + ', '.join(bad)); \
[print(' ', k, '->', d[k].get('error')) for k in bad]; \
sys.exit(1 if bad else 0)"

# Платный opt-in smoke: валидирует только статические схемы и выполняет два
# синтетических function-round непосредственно через GigaChat, без failover.
smoke-gigachat-tools:
	@uv run --project agents --frozen python scripts/check_gigachat_ca.py
	@docker exec -e GIGACHAT_SMOKE_MODEL=$(GIGACHAT_SMOKE_MODEL) gpthub-$(MODE)-agents-1 \
		python -m service.presentation.cli.gigachat_tools_smoke

# Платный opt-in E2E: backend создаёт отдельную временную песочницу и передаёт
# capability в agents только через stdin. Payload не печатается; cleanup выполняется
# также при ошибке smoke. Выбор ws_write/ws_read делает production selector+latch.
smoke-gigachat-workspace:
	@payload=$$(mktemp); \
	  cleanup() { \
	    if [ -s "$$payload" ]; then \
	      cat "$$payload" | docker exec -i gpthub-$(MODE)-backend-1 \
	        python -m service.utils.gigachat_workspace_fixture cleanup >/dev/null; \
	    fi; \
	    rm -f "$$payload"; \
	  }; \
	  trap cleanup EXIT INT TERM; \
	  docker exec gpthub-$(MODE)-backend-1 \
	    python -m service.utils.gigachat_workspace_fixture provision > "$$payload"; \
	  cat "$$payload" | docker exec -i -e GIGACHAT_SMOKE_MODEL=$(GIGACHAT_SMOKE_MODEL) \
	    gpthub-$(MODE)-agents-1 \
	    python -m service.presentation.cli.gigachat_workspace_smoke

# Полная opt-in сертификация: authoritative /models, schema validation, forced
# continuation и production selector/latch над изолированной sandbox.
smoke-gigachat-qualification:
	@uv run --project agents --frozen python scripts/check_gigachat_ca.py
	@payload=$$(mktemp); \
	  cleanup() { \
	    if [ -s "$$payload" ]; then \
	      cat "$$payload" | docker exec -i gpthub-$(MODE)-backend-1 \
	        python -m service.utils.gigachat_workspace_fixture cleanup >/dev/null; \
	    fi; \
	    rm -f "$$payload"; \
	  }; \
	  trap cleanup EXIT INT TERM; \
	  docker exec gpthub-$(MODE)-backend-1 \
	    python -m service.utils.gigachat_workspace_fixture provision > "$$payload"; \
	  cat "$$payload" | docker exec -i -e GIGACHAT_SMOKE_MODEL=$(GIGACHAT_SMOKE_MODEL) \
	    gpthub-$(MODE)-agents-1 \
	    python -m service.presentation.cli.gigachat_qualification_smoke

test:
	@echo "Running all tests (backend + frontend)..."
	@echo "Running backend tests..."
	cd backend && uv run --frozen pytest
	@echo "Running frontend integration tests..."
	if [ -d frontend ] && command -v npm >/dev/null 2>&1; then \
		cd frontend && npm run test:integration -- --passWithNoTests; \
	else \
		echo "Skipping frontend integration tests: npm not available in this environment"; \
	fi
	@echo "Running frontend e2e tests..."
	if [ -d frontend ] && command -v npm >/dev/null 2>&1; then \
		cd frontend && npm run e2e:run; \
	else \
		echo "Skipping frontend e2e tests: npm not available in this environment"; \
	fi

lint:
	@echo "Running pre-commit hooks..."
	# Без `|| true`: линт, который не может упасть, ничего не держит. Раньше и эта
	# строка, и frontend-линт глушили результат — `make lint` был зелёным всегда.
	# ESLint и снапшоты фронта теперь идут хуками pre-commit, отдельного вызова не нужно.
	pre-commit run --all-files

hooks:
	@echo "Installing pre-commit hooks (superproject + submodules)..."
	# Конфиг без установки — документация. Отдельная цель, потому что забыть это
	# означает работать вообще без обязательных проверок.
	#
	# ⚠️ Обход по сабмодулям обязателен: каждый из них — самостоятельный
	# git-репозиторий со своим .git, и хуки суперпроекта на коммит ВНУТРИ
	# сабмодуля не срабатывают. А код вносится именно там.
	#
	# ⚠️ frontend В СПИСКЕ БЫЛ ПРОПУЩЕН: конфиг у него появился вместе с gitleaks,
	# а установку сюда не дописали — то есть сканер секретов у фронта не отработал
	# НИ РАЗУ. Проверять глазами бесполезно (у сабмодуля `.git` — файл, а не
	# каталог): смотреть надо `git -C <m> rev-parse --absolute-git-dir`/hooks/.
	#
	# ldr и memos сюда НЕ входят намеренно: у них конфиги АПСТРИМА (458 и 51
	# строка чужих правил), а не наши. Ставить их — значит навязать форку чужой
	# регламент, который мы не собираемся соблюдать.
	pre-commit install
	@for m in backend agents duckdb graphify opendataloader whisper frontend; do \
	  if [ -f "$$m/.pre-commit-config.yaml" ]; then \
	    (cd "$$m" && pre-commit install >/dev/null && echo "  $$m: установлено"); \
	  else \
	    echo "  $$m: конфига нет — пропуск"; \
	  fi; \
	done


run:
	@echo "Running services via docker/run.sh (defaults to --dev)"
	@if [ -x docker/run.sh ]; then \
	  MEMOS=$(MEMOS) LDR=$(LDR) docker/run.sh --$(MODE); \
	else \
	  echo "run.sh not found or not executable"; exit 1; \
	fi

stop:
	@echo "Stopping services via docker/run.sh --stop"
	@if [ -x docker/run.sh ]; then \
	  docker/run.sh --stop; \
	else \
	  echo "run.sh not found or not executable"; exit 1; \
	fi

frontend-analyze:
	@echo "Run frontend bundle analysis (source-map-explorer)..."
	cd frontend && npm run build:analyze

# Граф знаний — дев-инструмент: агенты (и люди) спрашивают граф вместо грепа по
# файлам. Разбор чисто AST-овый: ни одного обращения к LLM, ключи не нужны.
#   make graph                    # по сервису (по умолчанию backend)
#   make graph GRAPH_TARGET=agents
#   make graph GRAPH_TARGET=.     # весь монорепо, кросс-сервисные связи
#
# ⚠️ Вывод кладётся В САМ СЕРВИС (`<цель>/graphify-out/`), а не в корень. Раньше он
# всегда падал в корень суперпроекта: 19 МБ артефактов одного сервиса лежали общей
# кучей, а собрать граф по второму значило затереть первый. Игнор прописан в
# .gitignore КАЖДОГО сабмодуля — корневой на них не действует, они для суперпроекта
# гитлинки.
#
# Цель по умолчанию — backend, а не `.`: полный монорепо тянет memos и ldr (вендорные
# форки на десятки тысяч файлов) и строится минутами. Кросс-сервисный граф остаётся
# доступен явным `GRAPH_TARGET=.`.
GRAPH_TARGET ?= backend
graph:
	@command -v graphify >/dev/null 2>&1 || { \
	  echo "graphify не установлен. Поставьте: uv tool install graphifyy"; \
	  echo "(пакет называется graphifyy — с ДВУМЯ y; команда при этом graphify)"; exit 1; }
	@echo "Строю граф по $(GRAPH_TARGET) (AST, без LLM)..."
	graphify extract $(GRAPH_TARGET) --code-only --out $(GRAPH_TARGET)
	graphify cluster-only $(GRAPH_TARGET)
	@echo "Готово: $(GRAPH_TARGET)/graphify-out/graph.html"

# Create (or reset) a DEV user with a VERIFIED email + password, so /login works
# without the OTP flow. Handy for local development, E2E runs and per-user graphify
# graphs (namespace user-<id>). Idempotent: repeating for the same email resets the
# password and re-verifies. Requires the stack running (backend + postgres).
#   make create-user EMAIL=dev@example.com PASSWORD=devpass123            # dev
#   make create-user EMAIL=dev@example.com PASSWORD=devpass123 MODE=prod  # prod
create-user:
	@if [ -z "$(EMAIL)" ] || [ -z "$(PASSWORD)" ]; then \
	  echo "Usage: make create-user EMAIL=you@example.com PASSWORD=secret123 [MODE=dev|prod]"; exit 2; fi
	@case "$(EMAIL)" in *\'*|*\\*|*" "*) echo "Refused: suspicious email '$(EMAIL)'"; exit 2;; esac
	@docker exec -i gpthub-$(MODE)-backend-1 python - "$(EMAIL)" "$(PASSWORD)" \
	  < backend/scripts/create_dev_user.py

# Promote an existing account to administrator by email (DB flag profile.user.is_admin).
# The account must already exist; the stack must be running (needs the postgres container).
#   make grant-admin EMAIL=user@example.com            # dev
#   make grant-admin EMAIL=user@example.com MODE=prod  # prod
grant-admin:
	@if [ -z "$(EMAIL)" ]; then echo "Usage: make grant-admin EMAIL=user@example.com [MODE=dev|prod]"; exit 2; fi
	@case "$(EMAIL)" in *\'*|*\\*|*" "*) echo "Refused: suspicious email '$(EMAIL)'"; exit 2;; esac
	@echo "Promoting $(EMAIL) to admin (mode=$(MODE))..."
	@out=$$(docker exec gpthub-$(MODE)-postgres-1 psql -U postgres -d main -v ON_ERROR_STOP=1 \
	  -c "UPDATE profile.\"user\" SET is_admin = true WHERE lower(email) = lower('$(EMAIL)');" 2>&1); \
	 echo "$$out" | grep -q "UPDATE 1" \
	   && echo "OK: $(EMAIL) is now an administrator (re-login to refresh the session)." \
	   || { echo "FAILED: no account with email $(EMAIL) — nothing changed."; echo "$$out"; exit 1; }

# Revoke administrator rights by email (inverse of grant-admin).
#   make revoke-admin EMAIL=user@example.com [MODE=dev|prod]
revoke-admin:
	@if [ -z "$(EMAIL)" ]; then echo "Usage: make revoke-admin EMAIL=user@example.com [MODE=dev|prod]"; exit 2; fi
	@case "$(EMAIL)" in *\'*|*\\*|*" "*) echo "Refused: suspicious email '$(EMAIL)'"; exit 2;; esac
	@echo "Revoking admin from $(EMAIL) (mode=$(MODE))..."
	@out=$$(docker exec gpthub-$(MODE)-postgres-1 psql -U postgres -d main -v ON_ERROR_STOP=1 \
	  -c "UPDATE profile.\"user\" SET is_admin = false WHERE lower(email) = lower('$(EMAIL)');" 2>&1); \
	 echo "$$out" | grep -q "UPDATE 1" \
	   && echo "OK: $(EMAIL) is no longer an administrator." \
	   || { echo "FAILED: no account with email $(EMAIL) — nothing changed."; echo "$$out"; exit 1; }
