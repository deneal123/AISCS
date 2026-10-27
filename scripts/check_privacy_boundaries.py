#!/usr/bin/env python3
"""Static guard for high-risk transport and migration diagnostics.

This is intentionally narrow: it protects the exact seams where a regression
would expose credentials or provider/user payloads before runtime tests can
sanitize them.  It is not a general secret scanner and never reads environment
files.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULES: tuple[tuple[str, Path, re.Pattern[str]], ...] = (
    (
        "billing_metrics_raw_failure",
        ROOT / "backend/service/services/billing/application/cost_guard_metrics.py",
        re.compile(r"logger\.exception\s*\(|exc_info\s*=\s*True|str\(exc\)"),
    ),
    (
        "background_manager_raw_failure",
        ROOT / "backend/service/utils/background_task_manager.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|logger\.[a-z]+\([^)]*\btask_name\b",
            re.DOTALL,
        ),
    ),
    (
        "provider_key_service_raw_diagnostics",
        ROOT / "backend/service/services/admin/application/provider_key_service.py",
        re.compile(
            r"exc_info\s*=\s*True|logger\.exception\s*\(|logger\.[a-z]+\([^\n]*updated_by"
        ),
    ),
    (
        "application_lifecycle_raw_failure",
        ROOT / "backend/service/utils/app_lifespan.py",
        re.compile(
            r"exc_info\s*=\s*True|logger\.exception\s*\(|str\(exc\)|"
            r"logger\.[a-z]+\([^\n]*,\s*exc\b",
        ),
    ),
    (
        "artifact_history_raw_failure",
        ROOT / "backend/service/services/chat/persistence/chat_persistence_service.py",
        re.compile(r"exc_info\s*=\s*True|logger\.[a-z]+\([^)]*\bkey\b", re.DOTALL),
    ),
    (
        "memory_service_raw_failure",
        ROOT / "backend/service/services/analytics/application/memory/service.py",
        re.compile(r"exc_info\s*=\s*True|logger\.exception\s*\(|type\(exc\)\.__name__"),
    ),
    (
        "memory_integration_raw_failure",
        ROOT / "backend/service/infrastructure/memory/base.py",
        re.compile(r"exc_info\s*=\s*True|logger\.[a-z]+\([^\n]*,\s*exc\b"),
    ),
    (
        "memory_error_class_payload",
        ROOT / "backend/service/infrastructure/memory/memos.py",
        re.compile(r"type\(exc\)\.__name__|exc_info\s*=\s*True"),
    ),
    (
        "provider_policy_raw_diagnostics",
        ROOT / "backend/service/infrastructure/provider_policy_store.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|"
            r"logger\.(?:debug|info|warning|error|critical)\s*\(",
        ),
    ),
    (
        "redis_cache_raw_diagnostics",
        ROOT / "backend/service/infrastructure/cache/cache.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|"
            r"logger\.[a-z]+\([^)]*\b(?:key|raw|payload|identifier|namespace)\b",
            re.DOTALL,
        ),
    ),
    (
        "file_scanner_raw_diagnostics",
        ROOT / "backend/service/services/files/application/scanning/service.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|"
            r"logger\.[a-z]+\([^)]*\bfile_key\b|str\(e\)",
            re.DOTALL,
        ),
    ),
    (
        "file_scan_worker_raw_diagnostics",
        ROOT / "backend/service/utils/file_scan_worker.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|"
            r"logger\.[a-z]+\([^)]*,\s*(?:file_key|result)\b",
            re.DOTALL,
        ),
    ),
    (
        "workspace_maintenance_traceback",
        ROOT / "workspace" / "service" / "application" / "lifecycle.py",
        re.compile(r"logger\.exception\s*\(|exc_info\s*=\s*True"),
    ),
    (
        "workspace_container_diagnostics",
        ROOT / "workspace" / "service" / "drivers" / "docker_cli.py",
        re.compile(r"logger\.[a-z]+\([^\n]*container_id"),
    ),
    (
        "repository_raw_failure_logging",
        ROOT
        / "backend"
        / "service"
        / "shared"
        / "repositories"
        / "decorators"
        / "session_processor.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|logger\.[a-z]+\([^\n]*,\s*exc\b"
        ),
    ),
    (
        "alembic_dsn_output",
        ROOT / "backend" / "alembic" / "env.py",
        re.compile(
            r"print\([^\n]*(?:sqlalchemy\.url|current_url|database_url)", re.IGNORECASE
        ),
    ),
    (
        "worker_raw_exception_result",
        ROOT
        / "backend"
        / "service"
        / "services"
        / "chat"
        / "infrastructure"
        / "chat_worker_tasks.py",
        re.compile(r'["\']error["\']\s*:\s*str\s*\(\s*exc'),
    ),
    (
        "worker_traceback_logging",
        ROOT
        / "backend"
        / "service"
        / "services"
        / "chat"
        / "infrastructure"
        / "chat_worker_tasks.py",
        re.compile(r"\b(?:exc_info\s*=\s*True|logger\.exception\s*\()"),
    ),
    (
        "sidecar_raw_http_body",
        ROOT
        / "backend"
        / "service"
        / "infrastructure"
        / "agents_client"
        / "http_agent_engine.py",
        re.compile(r"logger\.[a-z]+\([^\n]*(?:response|resp)\.text", re.IGNORECASE),
    ),
    (
        "chat_upload_raw_diagnostics",
        ROOT / "backend/service/services/chat/presentation/http/upload_api.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|"
            r"logger\.[a-z]+\([^)]*\b(?:filename|user_id)\b",
            re.DOTALL,
        ),
    ),
    (
        "attachment_persistence_raw_diagnostics",
        ROOT
        / "backend/service/services/chat/application/use_cases/upload_file_use_case.py",
        re.compile(
            r"logger\.exception\s*\(|exc_info\s*=\s*True|"
            r"logger\.[a-z]+\([^)]*\b(?:filename|user_id)\b",
            re.DOTALL,
        ),
    ),
)

_AGENTS_CLIENT_DIR = ROOT / "backend" / "service" / "infrastructure" / "agents_client"
SCOPED_LOG_FUNCTIONS = (
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "recall_last_thread_image_url",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "_recall_or_persist_thread_tabular",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "_forget_thread_files",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/repository_references.py",
        "read_thread_repo_graphs",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "collect_message_extras",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "_presign",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "_dialog_file_rows",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "_report_missing_rows",
    ),
    (
        ROOT / "backend/service/services/chat/infrastructure/agent_context.py",
        "_file_is_tabular",
    ),
    (
        ROOT / "backend/service/services/admin/application/runtime_settings.py",
        "_refresh_in_background",
    ),
    (
        ROOT / "backend/service/services/admin/application/admin_service.py",
        "_cascade_memos_embedder",
    ),
    (
        ROOT / "backend/service/services/admin/application/runtime_settings.py",
        "refresh",
    ),
    (
        ROOT / "backend/service/services/admin/application/admin_service.py",
        "_invalidate_profile_cache",
    ),
    (
        ROOT / "backend/service/services/admin/application/admin_service.py",
        "is_admin",
    ),
    (
        ROOT / "backend/service/services/admin/application/admin_service.py",
        "get_settings_view",
    ),
    (
        ROOT / "backend/service/services/admin/application/admin_service.py",
        "prime_provider_health",
    ),
)
_CHAT_WORKER_DIR = (
    ROOT
    / "backend"
    / "service"
    / "services"
    / "chat"
    / "infrastructure"
    / "chat_worker"
)
_FIXED_BOUNDARY_LOG_FILES = (
    ROOT / "backend/service/infrastructure/llm_gateway.py",
    ROOT / "backend/service/services/analytics/application/memory/service.py",
    ROOT / "backend" / "service" / "infrastructure" / "workspace_client.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "chat"
    / "infrastructure"
    / "chat_worker_tasks.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "chat"
    / "application"
    / "chat_application_service.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "chat"
    / "presentation"
    / "routers"
    / "chat_api"
    / "chat_api.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "chat"
    / "presentation"
    / "ws"
    / "chat_ws"
    / "metrics.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "chat"
    / "presentation"
    / "routers"
    / "chat_api"
    / "work_intake.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "files"
    / "application"
    / "file_saver_service.py",
    ROOT
    / "backend"
    / "service"
    / "services"
    / "files"
    / "persistence"
    / "file_repository.py",
    ROOT / "backend/service/services/files/infrastructure/maintenance.py",
)
BOUNDARY_LOG_FILES = tuple(
    dict.fromkeys(
        (
            *_FIXED_BOUNDARY_LOG_FILES,
            *sorted((ROOT / "backend/service/infrastructure/memory").glob("*.py")),
            *sorted(_AGENTS_CLIENT_DIR.rglob("*.py")),
            *sorted(_CHAT_WORKER_DIR.rglob("*.py")),
            *sorted((ROOT / "agents/service/infrastructure/harness").rglob("*.py")),
            *sorted((ROOT / "backend/service/infrastructure/ide").rglob("*.py")),
            *sorted((ROOT / "backend/service/services/analytics/application/memory").rglob("*.py")),
            *sorted((ROOT / "backend/service/services/chat/persistence/harness").rglob("*.py")),
            *sorted((ROOT / "workspace" / "service").rglob("*.py")),
        )
    )
)
UNSAFE_BOUNDARY_LOG = re.compile(
    r"logger\.(?:debug|info|warning|error|exception)\([^\n]*"
    r"(?:exc_info\s*=|str\s*\(\s*exc|response\.text|\.detail|workspace_id|filename|"
    r"job_id|user_id|file_id|file_key|file_name|file_metadata|\bpath\b|\bdsn\b|"
    r"password|secret|authorization|api_key|credential|\bprompt\b|\barguments\b|"
    r"\brequest\b|\bresponse\b|\bbody\b|\burl\b)",
    re.IGNORECASE,
)


def has_unsafe_workspace_log(source: str) -> bool:
    """Detect multiline traceback/identity logging without reading runtime data."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
            continue
        if node.func.attr not in {
            "debug",
            "info",
            "warning",
            "error",
            "exception",
            "critical",
        }:
            continue
        if node.func.attr == "exception":
            return True
        for keyword in node.keywords:
            if keyword.arg == "exc_info" and not (
                isinstance(keyword.value, ast.Constant)
                and keyword.value.value in (False, None)
            ):
                return True
        if any(
            isinstance(value, ast.Attribute) and value.attr == "container_id"
            for value in ast.walk(node)
        ):
            return True
    return False


def main() -> int:
    failures: list[str] = []
    for name, path, pattern in RULES:
        if not path.is_file():
            failures.append(f"{name}: missing guarded file {path.relative_to(ROOT)}")
            continue
        source = path.read_text(encoding="utf-8")
        if pattern.search(source):
            failures.append(
                f"{name}: forbidden diagnostic pattern in {path.relative_to(ROOT)}"
            )
    for path in BOUNDARY_LOG_FILES:
        if not path.is_file():
            failures.append(
                f"boundary_log: missing guarded file {path.relative_to(ROOT)}"
            )
            continue
        source = path.read_text(encoding="utf-8")
        if UNSAFE_BOUNDARY_LOG.search(source) or (
            path.is_relative_to(ROOT / "workspace") and has_unsafe_workspace_log(source)
        ):
            failures.append(
                f"boundary_log: unsafe payload logging in {path.relative_to(ROOT)}"
            )
    for path, function in SCOPED_LOG_FUNCTIONS:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            source = ""
        if has_unsafe_scoped_log(source, function):
            failures.append(
                f"scoped_log: unsafe or missing {path.relative_to(ROOT)}:{function}"
            )
    if failures:
        print("privacy boundary gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(
        "privacy boundary gate passed: "
        f"{len(RULES)} direct rules, {len(BOUNDARY_LOG_FILES)} integration log files, "
        f"{len(SCOPED_LOG_FUNCTIONS)} scoped functions"
    )
    return 0


def has_unsafe_scoped_log(source: str, function: str) -> bool:
    """Guard a migrated method without silently waiving its unmigrated siblings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function
    ]
    if len(matches) != 1:
        return True
    segment = ast.get_source_segment(source, matches[0])
    return (
        segment is None
        or has_unsafe_workspace_log(segment)
        or bool(UNSAFE_BOUNDARY_LOG.search(segment))
    )


if __name__ == "__main__":
    raise SystemExit(main())
