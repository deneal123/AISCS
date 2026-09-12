"""Контракт сайдкара workspace: то, на что опирается вызывающий.

Только stdlib — по той же причине, что у duckdb и agents: сверку гоняет офлайн-гейт CI, и
тянуть ради нескольких множеств строк docker-клиент он не должен.

🔴 ГЛАВНОЕ РАЗЛИЧЕНИЕ ЭТОГО СЕРВИСА — СТАТИЧЕСКАЯ И ГОРЯЧАЯ ПОЛОВИНЫ ПОЛИТИКИ. Статическая
(образ, сеть, права на файловую систему, потолки памяти и процессов) запирается в момент
создания и не меняется НИКОГДА; горячая (таймаут вызова, потолок вывода) правится на живой
песочнице. Различение не про удобство: право на файловую систему, доехавшее до работающего
контейнера, — это повышение привилегий по расписанию.
"""

from __future__ import annotations

import os

# Версия КОНТРАКТА, не образа. Поднимать при несовместимом изменении формы запроса/ответа.
SERVICE_VERSION = "1.1.0"
SERVICE_NAME = "workspace"

# 🔴 Поля политики, ЗАПЕРТЫЕ при создании. Попытка изменить любое на живой песочнице —
# отказ `static_policy_locked`, а не молчаливое применение части изменений.
STATIC_POLICY_FIELDS = frozenset(
    {
        "image",
        "network",
        "read_only_root",
        "memory_bytes",
        "pids_limit",
        "cpus",
        "user",
        "quota_bytes",
        "root",
    }
)

# Поля, которые можно править на работающей песочнице: они ограничивают ОДИН вызов, а не
# то, до чего вызов дотягивается.
DYNAMIC_POLICY_FIELDS = frozenset({"exec_timeout_sec", "max_output_chars"})

# Ключи успешного ответа. Вызывающий читает через `.get(...)`: переименование не падает, а
# тихо отдаёт пустоту — поэтому набор сверяется тестом с реально отдаваемыми словарями.
CREATE_RESPONSE_FIELDS = frozenset({"workspace_id", "token", "root", "expires_at", "policy"})
EXEC_RESPONSE_FIELDS = frozenset(
    {"exit_code", "stdout", "stderr", "truncated", "duration_sec", "timed_out"}
)
VIEW_RESPONSE_FIELDS = frozenset(
    {"entries", "history", "truncated", "root", "revision", "recovered"}
)

# Машинные коды ошибок: вызывающий различает случаи по КОДУ, а не по тексту `detail`.
ERROR_CODES = frozenset(
    {
        "invalid_request",  # 422 — тело не прошло схему
        "not_found",  # legacy/nested 404 retained for rolling compatibility
        "workspace_not_found",  # 404 — owning sandbox is proven absent or expired
        "unauthorized",  # 401 — нет ключа сервиса
        "forbidden",  # 403 — токен владения не подошёл
        "static_policy_locked",  # 409 — правка запертого поля политики
        "workspace_conflict",  # 409 — stale optimistic revision
        "isolation_unverified",  # 500 — заявленная изоляция не подтвердилась
        "quota_exceeded",  # 413
        "request_too_large",  # 413
        "exec_timeout",  # 504
        "workspace_unavailable",  # 503 - temporary coordinator/sidecar transport failure
        "driver_failed",  # 502 — не смогли создать/выполнить
        "invalid_project",
        "profile_missing",
        "profile_mismatch",
        "project_exists",
        "target_path_required",
        "source_changed",
        "build_timeout",
        "build_cancelled",
        "compile_failed",
        "audit_failed",
        "artifact_too_large",
        "artifact_invalid",
        "runtime_unavailable",
        "build_missing",
        "build_interrupted",
        "audit_busy",
        "audit_unavailable",
        "visual_unavailable",
        "visual_interrupted",
        "visual_render_failed",
        "visual_audit_failed",
        "vendor_archive_invalid",
        "vendor_manifest_invalid",
        "vendor_unsafe",
        "vendor_too_large",
        "vendor_collision",
        "vendor_source_unavailable",
        "vendor_integrity",
        "vendor_profile_invalid",
        "authoring_invalid",
        "authoring_missing",
        "authoring_publish_failed",
        "source_too_large",
        "internal",  # 500
    }
)

# Потолок тела запроса. Файлы внутрь едут ССЫЛКАМИ (сайдкар качает сам), поэтому тело
# маленькое: большое тело здесь означало бы, что кто-то шлёт байты не тем каналом.
MAX_BODY_BYTES = int(os.environ.get("WORKSPACE_MAX_BODY_BYTES", str(4 * 1024 * 1024)))

# Дефолты горячей половины политики.
DEFAULT_EXEC_TIMEOUT_SEC = float(os.environ.get("WORKSPACE_EXEC_TIMEOUT_SEC", "120"))
# ⚠️ Жёсткий потолок ОТДЕЛЬНО от дефолта: без него вызывающий выставил бы себе час и
# занял бы исполнителя, которого делят все арендаторы.
HARD_EXEC_TIMEOUT_SEC = float(os.environ.get("WORKSPACE_HARD_EXEC_TIMEOUT_SEC", "600"))
DEFAULT_MAX_OUTPUT_CHARS = int(os.environ.get("WORKSPACE_MAX_OUTPUT_CHARS", "20000"))

# Время жизни песочницы. Не «на всякий случай»: контейнер, который никто не удалил,
# занимает диск и память хоста до перезапуска демона.
DEFAULT_TTL_SEC = float(os.environ.get("WORKSPACE_TTL_SEC", "1800"))
HARD_TTL_SEC = float(os.environ.get("WORKSPACE_HARD_TTL_SEC", "14400"))

# Сколько песочниц держим одновременно. Потолок общий, а не на арендатора: ресурс хостовой.
MAX_WORKSPACES = int(os.environ.get("WORKSPACE_MAX_WORKSPACES", "32"))

# Образ рантайма песочницы. 🔴 НЕ ЛИТЕРАЛ В ПОЛИТИКЕ: истории версий (`ws_log`/`ws_diff`/
# `ws_revert`) нужен `git`, которого в голом `python:*-slim` нет. Какой образ подан — это
# решение развёртывания, и оно должно приниматься в одном месте, а не выясняться по
# провалу первой же команды. Дефолт — собираемый нами `runtime.Dockerfile` (slim + git).
DEFAULT_IMAGE = str(os.environ.get("WORKSPACE_IMAGE", "gpthub-workspace-runtime:latest"))
# Личность коммиттера: без неё `git commit` в контейнере без конфига просто ОТКАЗЫВАЕТСЯ,
# и история молча не ведётся.
GIT_AUTHOR = str(os.environ.get("WORKSPACE_GIT_AUTHOR", "GPTHub Agent <agent@gpthub.local>"))
