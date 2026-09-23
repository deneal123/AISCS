"""Native Document Forge tools backed by the isolated workspace compiler."""

from __future__ import annotations

import json

from agents import FunctionTool, RunContextWrapper

from service.domain.capabilities.tool_spec import (
    EFFECT_READ_ONLY,
    EFFECT_WORKSPACE_MUTATION,
    GROUNDING_WORKSPACE,
    ToolSpec,
)
from service.domain.documents import audit_document_build
from service.domain.run_context import require_execution
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools import unbilled_calls
from service.domain.tools.workspace_client import WorkspaceUnavailable, call
from service.domain.tools.workspace_tool_specs import BILLING_NAME, CONTEXT_ATTR, ENABLED_FIELD

_PATH = {
    "type": "string",
    "description": "Относительный путь проекта LaTeX в рабочем месте.",
    "minLength": 1,
    "maxLength": 1024,
}
_BUILD_ID = {
    "type": "string",
    "description": "Непрозрачный идентификатор сборки из tex_compile.",
    "minLength": 8,
    "maxLength": 128,
}


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _ref(ctx: RunContextWrapper):
    context = getattr(ctx, "context", None)
    if isinstance(context, dict):
        return context.get("workspace_ref")
    return getattr(context, "workspace_ref", None)


def _args(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _failure(exc: WorkspaceUnavailable) -> ToolCallOutcome:
    unbilled_calls.waive(BILLING_NAME)
    code = {
        "timeout": ToolFailureCode.TIMEOUT,
        "transport": ToolFailureCode.TRANSPORT,
        "remote": ToolFailureCode.REMOTE,
        "protocol": ToolFailureCode.PROTOCOL,
        "conflict": ToolFailureCode.CONFLICT,
        "expired": ToolFailureCode.UNAVAILABLE,
        "unavailable": ToolFailureCode.UNAVAILABLE,
        "invalid": ToolFailureCode.INVALID_ARGUMENTS,
        "cancelled": ToolFailureCode.CANCELLED,
        "policy": ToolFailureCode.POLICY,
    }.get(exc.reason_code, ToolFailureCode.INTERNAL)
    return ToolCallOutcome(
        exc.model_message(),
        "failed",
        0.0,
        retryable=exc.retryable,
        billable=False,
        failure_code=code,
    )


async def _invoke(ctx: RunContextWrapper, raw: str, endpoint: str) -> str | ToolCallOutcome:
    try:
        result = await call(_ref(ctx), endpoint, _args(raw))
        return json.dumps(result, ensure_ascii=False)
    except WorkspaceUnavailable as exc:
        return _failure(exc)


async def tex_profiles_tool(ctx: RunContextWrapper, raw: str):
    return await _invoke(ctx, raw, "documents/profiles")


async def tex_project_create_tool(ctx: RunContextWrapper, raw: str):
    return await _invoke(ctx, raw, "documents")


async def tex_project_status_tool(ctx: RunContextWrapper, raw: str):
    return await _invoke(ctx, raw, "documents/status")


async def tex_profile_apply_tool(ctx: RunContextWrapper, raw: str):
    payload = _args(raw)
    endpoint = (
        "documents/vendor/activate" if payload.get("vendor_package_id") else "documents/profile"
    )
    try:
        result = await call(_ref(ctx), endpoint, payload)
        return json.dumps(result, ensure_ascii=False)
    except WorkspaceUnavailable as exc:
        return _failure(exc)


async def tex_compile_tool(ctx: RunContextWrapper, raw: str):
    return await _invoke(ctx, raw, "documents/builds")


async def tex_build_status_tool(ctx: RunContextWrapper, raw: str):
    build_id = str(_args(raw).get("build_id") or "")
    return await _invoke(ctx, raw, f"documents/builds/{build_id}")


async def tex_build_cancel_tool(ctx: RunContextWrapper, raw: str):
    build_id = str(_args(raw).get("build_id") or "")
    return await _invoke(ctx, raw, f"documents/builds/{build_id}/cancel")


async def tex_inspect_tool(ctx: RunContextWrapper, raw: str):
    build_id = str(_args(raw).get("build_id") or "")
    try:
        ref = _ref(ctx)
        status = await call(ref, f"documents/builds/{build_id}", {})
        if status.get("state") == "visual_pending":
            await audit_document_build(ref, build_id, execution=require_execution())
            status = await call(ref, f"documents/builds/{build_id}", {})
        return json.dumps(status, ensure_ascii=False)
    except WorkspaceUnavailable as exc:
        return _failure(exc)


tex_profiles = FunctionTool(
    name="tex_profiles",
    description="Показать проверенные профили LaTeX для статей, презентаций и документов.",
    params_json_schema=_schema({}, []),
    on_invoke_tool=tex_profiles_tool,
)
tex_project_create = FunctionTool(
    name="tex_project_create",
    description="Создать безопасный LaTeX-проект из выбранного профиля.",
    params_json_schema=_schema(
        {
            "path": _PATH,
            "profile_id": {
                "type": "string",
                "description": "Идентификатор из tex_profiles.",
            },
            "mode": {
                "type": "string",
                "description": "Режим подготовки документа.",
                "enum": ["draft", "submission", "camera_ready"],
            },
            "locale": {"type": "string", "description": "Локаль документа, например ru-RU."},
        },
        ["path", "profile_id", "mode"],
    ),
    on_invoke_tool=tex_project_create_tool,
)
tex_project_status = FunctionTool(
    name="tex_project_status",
    description="Проверить профиль, режим и revision LaTeX-проекта.",
    params_json_schema=_schema({"path": _PATH}, ["path"]),
    on_invoke_tool=tex_project_status_tool,
)
tex_profile_apply = FunctionTool(
    name="tex_profile_apply",
    description="Сменить детерминированный профиль существующего LaTeX-проекта.",
    params_json_schema=_schema(
        {
            "path": _PATH,
            "profile_id": {
                "type": "string",
                "description": "Новый идентификатор из tex_profiles.",
                "minLength": 3,
                "maxLength": 64,
            },
            "vendor_package_id": {
                "type": "string",
                "description": (
                    "Optional installed project-local vendor v2 package. The source project "
                    "is cloned and probe-built before activation."
                ),
                "pattern": "^[a-z][a-z0-9_-]{2,63}$",
            },
            "target_path": {
                "type": "string",
                "description": "Новый путь клона; исходный проект не изменяется.",
                "minLength": 1,
                "maxLength": 1024,
            },
            "mode": {
                "type": "string",
                "description": "Режим подготовки документа.",
                "enum": ["draft", "submission", "camera_ready"],
            },
            "locale": {
                "type": "string",
                "description": "Локаль документа, например ru-RU или en-US.",
                "maxLength": 24,
            },
        },
        ["path", "profile_id", "target_path"],
    ),
    on_invoke_tool=tex_profile_apply_tool,
)
tex_compile = FunctionTool(
    name="tex_compile",
    description="Запустить изолированную сборку и аудит LaTeX-проекта.",
    params_json_schema=_schema(
        {
            "path": _PATH,
            "final": {
                "type": "boolean",
                "description": "Финальная сборка с разрешённым source bundle.",
            },
        },
        ["path", "final"],
    ),
    on_invoke_tool=tex_compile_tool,
)
tex_build_status = FunctionTool(
    name="tex_build_status",
    description="Получить bounded-статус и диагностику сборки документа.",
    params_json_schema=_schema({"build_id": _BUILD_ID}, ["build_id"]),
    on_invoke_tool=tex_build_status_tool,
)
tex_build_cancel = FunctionTool(
    name="tex_build_cancel",
    description="Отменить выполняющуюся сборку документа.",
    params_json_schema=_schema({"build_id": _BUILD_ID}, ["build_id"]),
    on_invoke_tool=tex_build_cancel_tool,
)
tex_inspect = FunctionTool(
    name="tex_inspect",
    description="Проверить страницы, геометрию, шрифты, ссылки и артефакты сборки.",
    params_json_schema=_schema({"build_id": _BUILD_ID}, ["build_id"]),
    on_invoke_tool=tex_inspect_tool,
)

_TOOLS = (
    (tex_profiles, EFFECT_READ_ONLY, "выбрать профиль PDF-документа"),
    (tex_project_create, EFFECT_WORKSPACE_MUTATION, "создать LaTeX-проект"),
    (tex_project_status, EFFECT_READ_ONLY, "проверить LaTeX-проект"),
    (tex_profile_apply, EFFECT_WORKSPACE_MUTATION, "сменить профиль LaTeX-проекта"),
    (tex_compile, EFFECT_WORKSPACE_MUTATION, "собрать и проверить PDF"),
    (tex_build_status, EFFECT_READ_ONLY, "узнать состояние сборки PDF"),
    (tex_build_cancel, EFFECT_WORKSPACE_MUTATION, "отменить сборку PDF"),
    (tex_inspect, EFFECT_READ_ONLY, "проверить техническое качество PDF"),
)

SPECS = [
    ToolSpec(
        name=tool.name,
        tool=tool,
        requires_context_attr=CONTEXT_ATTR,
        billing_name=BILLING_NAME,
        enabled_field=ENABLED_FIELD,
        source="workspace",
        selector_hint=hint,
        effect=effect,
        concurrency_group="workspace" if effect == EFFECT_WORKSPACE_MUTATION else None,
        grounding_roles=frozenset({GROUNDING_WORKSPACE}),
        default_timeout_sec=300.0 if tool.name == "tex_compile" else 90.0,
    )
    for tool, effect, hint in _TOOLS
]
