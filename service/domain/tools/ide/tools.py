"""Repository-scoped file tools. No shell, snapshots, Git commits or legacy binding."""

from __future__ import annotations

import hashlib
import json
import re

from agents import FunctionTool, RunContextWrapper

from service.domain.capabilities.tools.spec import (
    EFFECT_READ_ONLY,
    EFFECT_WORKSPACE_MUTATION,
    GROUNDING_WORKSPACE,
    ToolSpec,
)
from service.domain.execution.context import require_current_execution
from service.domain.integration_failure import IntegrationFailureCode
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools import unbilled_calls
from service.domain.tools.ide.commands import SPECS as COMMAND_SPECS
from service.domain.tools.ide.commands import TOOLS as COMMAND_TOOLS
from service.domain.tools.ide.finish import SPEC as FINISH_SPEC
from service.domain.tools.ide.finish import TOOL as FINISH_TOOL
from service.domain.tools.workspace.client import WorkspaceUnavailable, call
from service.domain.tools.workspace.tools import _failure
from service.shared.task_contract import FILE_PATH_PATTERN, NONEMPTY_FILE_PATH_PATTERN

MAX_FILES = 128
MAX_RESULT = 22000


def _execution():
    execution = require_current_execution()
    ref = execution.resources.workspace_ref
    if not isinstance(ref, dict) or not isinstance(ref.get("ide_context"), dict):
        raise ValueError("ide_context_required")
    return execution, ref


def _path(value):
    if (
        type(value) is not str
        or not 0 < len(value) <= 1024
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(
            part in {"", ".", "..", ".git", "node_modules", ".venv", "__pycache__", ".mypy_cache"}
            or part.startswith(".gpthub-")
            for part in value.split("/")
        )
    ):
        raise ValueError("invalid_path")
    return value


def _args(raw, keys):
    args = json.loads(raw)
    if type(args) is not dict or set(args) != set(keys):
        raise ValueError("invalid_arguments")
    return args


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _confirmed(value) -> ToolCallOutcome:
    """Only this adapter's validated read/write ACK may declare success."""
    return ToolCallOutcome(_json(value), "succeeded", 0.0)


def _reject(code):
    unbilled_calls.waive("workspace_tool")
    return ToolCallOutcome(
        _json({"error": code}),
        "failed",
        0.0,
        retryable=False,
        billable=False,
        failure_code=ToolFailureCode.INVALID_ARGUMENTS,
    )


def _read_result(value):
    if (
        type(value) is not dict
        or not {"path", "kind", "size", "content", "digest", "truncated"} <= value.keys()
        or value["kind"] not in {"text", "binary"}
        or type(value["size"]) is not int
        or value["size"] < 0
        or type(value["truncated"]) is not bool
    ):
        raise ValueError("invalid_response")
    if value["kind"] != "text" or value["truncated"]:
        return {
            "path": value["path"],
            "kind": value["kind"],
            "truncated": value["truncated"],
            "editable": False,
        }, None
    content, digest = value["content"], value["digest"]
    if (
        type(content) is not str
        or len(content.encode()) > 262144
        or type(digest) is not str
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or hashlib.sha256(content.encode()).hexdigest() != digest
        or value["size"] != len(content.encode())
    ):
        raise ValueError("invalid_response")
    result = {key: value[key] for key in ("path", "kind", "size", "content", "digest", "truncated")}
    length = len(content)
    while len(_json(result)) > MAX_RESULT:
        length = length * 3 // 4
        result.update(content=content[:length], truncated=True)
    result["editable"] = not result["truncated"]
    return result, {
        "content": content,
        "digest": digest,
        "shown": result["content"],
        "whole": not result["truncated"],
    }


async def ide_tree(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    try:
        execution, ref = _execution()
        args = _args(raw, ["path"])
        path = _path(args["path"]) if args["path"] else ""
        result = await call(ref, "ide/tree", {"path": path})
        entries = result.get("entries")
        if (
            type(entries) is not list
            or len(entries) > 400
            or type(result.get("truncated")) is not bool
        ):
            raise ValueError
        safe, size = [], 0
        truncated = result["truncated"]
        for row in entries:
            if row.get("type") not in {"file", "dir"}:
                raise ValueError
            row = {"path": _path(row["path"]), "type": row["type"]}
            size += len(_json(row)) + 1
            if size > MAX_RESULT - 200:
                truncated = True
                break
            safe.append(row)
        observed = {"entries": safe, "truncated": truncated}
        while len(execution.workspace.ide_trees) >= MAX_FILES:
            execution.workspace.ide_trees.pop(next(iter(execution.workspace.ide_trees)))
        execution.workspace.ide_trees[path] = {
            "digest": hashlib.sha256(_json(observed).encode()).hexdigest(),
            "whole": not truncated,
        }
        return _confirmed(observed)
    except WorkspaceUnavailable as error:
        return _failure(error)
    except (ValueError, TypeError, KeyError, AttributeError):
        return _reject("invalid_arguments_or_response")


async def ide_read(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    try:
        execution, ref = _execution()
        path = _path(_args(raw, ["path"])["path"])
        result = await call(ref, "ide/file", {"path": path})
        if result.get("path") != path:
            raise ValueError
        projected, evidence = _read_result(result)
        execution.workspace.ide_reads.pop(path, None)
        if evidence is not None:
            while len(execution.workspace.ide_reads) >= MAX_FILES:
                execution.workspace.ide_reads.pop(next(iter(execution.workspace.ide_reads)))
            execution.workspace.ide_reads[path] = evidence
        return _confirmed(projected)
    except WorkspaceUnavailable as error:
        return _failure(error)
    except (ValueError, TypeError, KeyError, AttributeError):
        return _reject("invalid_arguments_or_response")


async def _write(path, operation, content, digest):
    execution, ref = _execution()
    if execution.workspace.ide_unconfirmed:
        # A timeout is not proof that the previous write failed. Neither a model
        # retry nor another path may conceal unresolved effects in the same run.
        raise WorkspaceUnavailable(IntegrationFailureCode.POLICY)
    if (
        len(execution.workspace.ide_writes) >= MAX_FILES
        and path not in execution.workspace.ide_writes
    ):
        raise ValueError("operation_limit")
    if type(content) is not str or len(content.encode()) > 262144 or "\0" in content:
        raise ValueError
    execution.workspace.ide_reads.pop(path, None)
    execution.workspace.ide_trees.clear()
    # A report made before another attempted mutation is no longer terminal.
    execution.workspace.ide_summary = None
    try:
        result = await call(
            ref,
            "ide/agent/write",
            dict(path=path, operation=operation, content=content, expected_digest=digest),
        )
    except WorkspaceUnavailable as error:
        if error.reason_code not in {"conflict", "policy", "invalid", "expired"}:
            execution.workspace.ide_unconfirmed = True
        raise
    expected = dict(
        written=True,
        path=path,
        kind="dir" if operation == "directory" else "file",
        size=0 if operation == "directory" else len(content.encode()),
        digest=None if operation == "directory" else hashlib.sha256(content.encode()).hexdigest(),
    )
    if (
        result != expected
        or type(result.get("size")) is not int
        or result.get("written") is not True
    ):
        execution.workspace.ide_unconfirmed = True
        raise ValueError
    execution.workspace.ide_writes[path] = expected["digest"]
    return _confirmed(expected)


async def ide_write(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    try:
        execution, _ = _execution()
        args = _args(raw, ["path", "content", "base_digest"])
        path, digest = _path(args["path"]), args["base_digest"]
        if digest == "":
            digest = None
        if digest is not None:
            base = execution.workspace.ide_reads.get(path)
            if not base or not base["whole"] or digest != base["digest"]:
                return _reject("read_current_file_before_writing")
        return await _write(path, "file", args["content"], digest)
    except WorkspaceUnavailable as error:
        return _failure(error)
    except (ValueError, TypeError, KeyError):
        return _reject("write_not_confirmed")


async def ide_edit(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    try:
        execution, _ = _execution()
        args = _args(raw, ["path", "old", "new", "base_digest"])
        path = _path(args["path"])
        base = execution.workspace.ide_reads.get(path)
        if not base or args["base_digest"] != base["digest"]:
            return _reject("read_current_file_before_editing")
        old, new = args["old"], args["new"]
        if (
            type(old) is not str
            or type(new) is not str
            or not old
            or old not in base["shown"]
            or base["content"].count(old) != 1
        ):
            return _reject("old_fragment_must_be_observed_and_unique")
        return await _write(path, "file", base["content"].replace(old, new, 1), base["digest"])
    except WorkspaceUnavailable as error:
        return _failure(error)
    except (ValueError, TypeError, KeyError):
        return _reject("edit_not_confirmed")


async def ide_mkdir(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    try:
        return await _write(_path(_args(raw, ["path"])["path"]), "directory", "", None)
    except WorkspaceUnavailable as error:
        return _failure(error)
    except (ValueError, TypeError, KeyError):
        return _reject("directory_not_confirmed")


def _tool(name, description, handler, properties):
    return FunctionTool(
        name=name,
        description=description,
        on_invoke_tool=handler,
        params_json_schema=dict(
            type="object",
            properties=properties,
            required=list(properties),
            additionalProperties=False,
        ),
    )


PATH = {
    "type": "string",
    "pattern": NONEMPTY_FILE_PATH_PATTERN,
    "minLength": 1,
    "description": "Относительный путь внутри выбранного репозитория.",
}
DIGEST = {
    "type": "string",
    "description": "Digest из ide_read_file; пустая строка только для нового файла.",
}
TEXT = {"type": "string", "description": "Точный текст содержимого или заменяемого фрагмента."}
TOOLS = [
    _tool(
        "ide_list_files",
        "Прочитать дерево выбранного репозитория. Пустой path означает корень.",
        ide_tree,
        {"path": {**PATH, "minLength": 0, "pattern": FILE_PATH_PATTERN}},
    ),
    _tool(
        "ide_read_file",
        "Прочитать исходник и его digest. Truncated не означает, что показан весь файл.",
        ide_read,
        {"path": PATH},
    ),
    _tool(
        "ide_write_file",
        "Создать файл или записать полностью прочитанный файл по digest. Без Git-коммита.",
        ide_write,
        {"path": PATH, "content": TEXT, "base_digest": DIGEST},
    ),
    _tool(
        "ide_edit_file",
        "Заменить один наблюдавшийся уникальный фрагмент, сохранив остальной файл. Требует чтения.",
        ide_edit,
        {"path": PATH, "old": TEXT, "new": TEXT, "base_digest": DIGEST},
    ),
    _tool(
        "ide_create_directory",
        "Создать одну папку. Родитель должен существовать. Не запускает код.",
        ide_mkdir,
        {"path": PATH},
    ),
]
SPECS = [
    ToolSpec(
        name=tool.name,
        tool=tool,
        billing_name="workspace_tool",
        source="workspace",
        enabled_field="workspace_enabled",
        requires_context_attr="ide_tools_enabled",
        result_limit_chars=24000,
        effect=EFFECT_READ_ONLY
        if tool.name in {"ide_list_files", "ide_read_file"}
        else EFFECT_WORKSPACE_MUTATION,
        concurrency_group="workspace",
        grounding_roles=frozenset({GROUNDING_WORKSPACE}),
        selector_hint=tool.description,
    )
    for tool in TOOLS
]

# The terminal report is local and has no workspace-tool surcharge.
TOOLS.append(FINISH_TOOL)
SPECS.append(FINISH_SPEC)

TOOLS.extend(COMMAND_TOOLS)
SPECS.extend(COMMAND_SPECS)
