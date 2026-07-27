#!/usr/bin/env python3
"""Транспорт сайдкара workspace: файловая песочница для агента.

Логика — в `core.py`/`policy.py`/`drivers/`, границы контракта — в `contracts.py`.

  POST   /workspaces                  {user_id, ttl_sec, policy} → {workspace_id, token, …}
  POST   /workspaces/{id}/exec        {user_id, token, command}  → {exit_code, stdout, …}
  POST   /workspaces/{id}/files/list  {user_id, token, path}     → {entries, truncated}
  POST   /workspaces/{id}/files/read  {user_id, token, path}     → {content, truncated}
  POST   /workspaces/{id}/files/write {user_id, token, path, content} → {written}
  POST   /workspaces/{id}/files/grep  {user_id, token, pattern, path} → {matches, truncated}
  POST   /workspaces/{id}/import      {user_id, token, files:[{name,url}]} → {files, imported}
  POST   /workspaces/{id}/artifacts   {user_id, token}           → {artifacts, truncated}
  POST   /workspaces/{id}/files/download {user_id, token, path}   → {content_b64}
  PATCH  /workspaces/{id}/policy      {user_id, token, update}   → {policy}
  DELETE /workspaces/{id}             {user_id, token}           → {deleted}
  GET    /health                      → {status, service, version, contract, driver, …}

Форма ошибки одна на все сервисы: `{"error": "<машинный код>", "detail": "<текст>"}`.

🔴 ЭТОТ СЕРВИС — ЕДИНСТВЕННЫЙ, КОМУ ОТДАН `docker.sock`. Поэтому ручек ровно столько,
сколько нужно, и каждая требует и ключ сервиса (кто зовёт), и токен владения (чья песочница).
Разделение не избыточно: ключ общий на весь backend, а песочница принадлежит пользователю.
"""

import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from files import (
    MAX_DOWNLOAD_BYTES,
    MAX_READ_BYTES,
    UnsafePath,
    artifacts_command,
    download_command,
    grep_command,
    list_command,
    parse_artifacts,
    parse_download,
    parse_read,
    read_command,
    reject_control_bytes,
    write_command,
)
from importer import MAX_TOTAL_BYTES, ImportRefused, fetch, plan
from importer import write_command as import_command
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from contracts import (
    CREATE_RESPONSE_FIELDS,
    DEFAULT_TTL_SEC,
    ERROR_CODES,
    EXEC_RESPONSE_FIELDS,
    MAX_BODY_BYTES,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from core import TooManyWorkspaces, WorkspaceNotFound, WorkspaceRegistry
from drivers import DriverError, IsolationUnverified, build_driver, driver_names
from ownership import OwnershipError
from policy import StaticPolicyLocked, policy_from_request

PORT = int(os.environ.get("PORT", "8080"))
DRIVER = os.environ.get("WORKSPACE_DRIVER", "docker")
SERVICE_KEY = str(os.environ.get("WORKSPACE_API_KEY", "") or "")

logger = logging.getLogger("workspace-sidecar")

app = FastAPI(
    title="GPTHub workspace sidecar", version=SERVICE_VERSION, docs_url=None, redoc_url=None
)
registry: WorkspaceRegistry | None = None


def _error(code: str, detail: str, status: int) -> JSONResponse:
    assert code in ERROR_CODES, f"код ошибки {code!r} не объявлен в contracts.ERROR_CODES"
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


# ⚠️ Обработчики фреймворка — ЧАСТЬ КОНТРАКТА. Без них FastAPI отдаёт свою форму на 404 и
# 422, и сервис говорит двумя языками ошибок сразу.
@app.exception_handler(StarletteHTTPException)
async def _http_error(_request: Request, exc: StarletteHTTPException):
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 413: "request_too_large"}.get(
        exc.status_code, "internal"
    )
    return _error(code, str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError):
    return _error("invalid_request", str(exc.errors()[:3]), 422)


@app.middleware("http")
async def _limit_body(request: Request, call_next):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return _error("request_too_large", f"тело больше {MAX_BODY_BYTES} байт", 413)
    return await call_next(request)


def _auth(authorization: str | None) -> None:
    """Ключ сервиса. ⚠️ Пустой ключ в настройке = ручка открыта — это ОШИБКА СТАРТА, а не
    режим работы: сервису отдан docker.sock, и открытая ручка здесь равна доступу к хосту."""
    if not SERVICE_KEY:
        raise RuntimeError("WORKSPACE_API_KEY не задан — сервис с docker.sock не может быть открыт")
    expected = f"Bearer {SERVICE_KEY}"
    if str(authorization or "") != expected:
        raise StarletteHTTPException(status_code=401, detail="нужен ключ сервиса")


class CreateRequest(BaseModel):
    user_id: str
    ttl_sec: float = DEFAULT_TTL_SEC
    policy: dict | None = None


class ExecRequest(BaseModel):
    user_id: str
    token: str
    command: str = Field(min_length=1)


class PolicyRequest(BaseModel):
    user_id: str
    token: str
    update: dict


class OwnerRequest(BaseModel):
    user_id: str
    token: str


class ImportRequest(BaseModel):
    user_id: str
    token: str
    files: list[dict]


class FileRequest(BaseModel):
    user_id: str
    token: str
    path: str = ""
    content: str | None = None
    pattern: str | None = None


@app.post("/workspaces")
async def create_workspace(
    payload: CreateRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    try:
        policy = policy_from_request(payload.policy)
    except (TypeError, ValueError) as exc:
        return _error("invalid_request", str(exc), 422)
    try:
        item, token = await registry.create(payload.user_id, policy, ttl_sec=payload.ttl_sec)
    except TooManyWorkspaces as exc:
        return _error("quota_exceeded", str(exc), 413)
    except IsolationUnverified as exc:
        # 🔴 Наружу — прямым текстом: «песочница, которая не песочница» обязана быть видна.
        logger.error("изоляция не подтвердилась: %s", exc)
        return _error("isolation_unverified", str(exc), 500)
    except DriverError as exc:
        return _error("driver_failed", str(exc), 502)
    return {
        "workspace_id": item.workspace_id,
        "token": token,
        "root": item.policy.root,
        "expires_at": item.expires_at,
        "policy": item.policy.as_dict(),
    }


def _resolve(workspace_id: str, user_id: str, token: str):
    return registry.get(workspace_id, user_id, token)


@app.post("/workspaces/{workspace_id}/exec")
async def exec_in_workspace(
    workspace_id: str, payload: ExecRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    try:
        item = _resolve(workspace_id, payload.user_id, payload.token)
    except OwnershipError as exc:
        return _error("forbidden", str(exc), 403)
    except WorkspaceNotFound as exc:
        return _error("not_found", str(exc), 404)
    try:
        command = reject_control_bytes(payload.command, "команда")
    except UnsafePath as exc:
        # ⚠️ 422, а не 500: это негодный ВВОД, а не сбой сервиса. Раньше нулевой байт
        # ронял создание процесса, и наружу уходило нечитаемое «Internal Server Error».
        return _error("invalid_request", str(exc), 422)
    try:
        result = await registry.exec(item, command)
    except DriverError as exc:
        return _error("driver_failed", str(exc), 502)
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "truncated": result.truncated,
        "duration_sec": result.duration_sec,
        "timed_out": result.timed_out,
    }


@app.patch("/workspaces/{workspace_id}/policy")
async def update_policy(
    workspace_id: str, payload: PolicyRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    try:
        item = _resolve(workspace_id, payload.user_id, payload.token)
    except OwnershipError as exc:
        return _error("forbidden", str(exc), 403)
    except WorkspaceNotFound as exc:
        return _error("not_found", str(exc), 404)
    try:
        policy = await registry.update_policy(item, payload.update)
    except StaticPolicyLocked as exc:
        return _error("static_policy_locked", str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error("invalid_request", str(exc), 422)
    return {"policy": policy.as_dict()}


@app.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str, payload: OwnerRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    try:
        _resolve(workspace_id, payload.user_id, payload.token)
        await registry.destroy(workspace_id)
    except OwnershipError as exc:
        return _error("forbidden", str(exc), 403)
    except WorkspaceNotFound as exc:
        return _error("not_found", str(exc), 404)
    return {"deleted": workspace_id}


def _owned(workspace_id: str, payload):
    """Найти песочницу владельца или отдать готовый ответ об ошибке."""
    try:
        return _resolve(workspace_id, payload.user_id, payload.token), None
    except OwnershipError as exc:
        return None, _error("forbidden", str(exc), 403)
    except WorkspaceNotFound as exc:
        return None, _error("not_found", str(exc), 404)


async def _run_file_op(item, command: str):
    """Выполнить служебную команду файловой операции.

    ⚠️ Потолок вывода СВОЙ, а не из политики: у чтения файла и у вывода сборки разные
    задачи, и общий потолок молча обрезал бы первое под второе.
    """
    return await registry.exec_raw(item, command, max_output_chars=MAX_READ_BYTES * 2)


@app.post("/workspaces/{workspace_id}/files/list")
async def list_files(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        command = list_command(item.policy.root, payload.path)
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    result = await _run_file_op(item, command)
    entries = []
    for line in (result.stdout or "").splitlines():
        parts = line.split("	")
        if len(parts) == 3:
            entries.append({"type": parts[0], "size": int(parts[1] or 0), "path": parts[2]})
    return {"entries": entries, "truncated": result.truncated}


@app.post("/workspaces/{workspace_id}/files/read")
async def read_file(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        command = read_command(item.policy.root, payload.path)
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    result = await _run_file_op(item, command)
    try:
        content, truncated = parse_read(result.stdout)
    except FileNotFoundError:
        return _error("not_found", f"файла {payload.path!r} нет", 404)
    except ValueError as exc:
        return _error("driver_failed", f"чтение не удалось: {exc}", 502)
    return {"path": payload.path, "content": content, "truncated": truncated}


@app.post("/workspaces/{workspace_id}/files/write")
async def write_file(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        command = write_command(item.policy.root, payload.path, payload.content or "")
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    except ValueError as exc:
        return _error("request_too_large", str(exc), 413)
    result = await _run_file_op(item, command)
    if "__OK__" not in (result.stdout or ""):
        return _error("driver_failed", (result.stderr or "запись не удалась")[:300], 502)
    return {"path": payload.path, "written": True}


@app.post("/workspaces/{workspace_id}/files/grep")
async def grep_files(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    if not (payload.pattern or "").strip():
        return _error("invalid_request", "нужен непустой шаблон поиска", 422)
    try:
        command = grep_command(item.policy.root, payload.pattern, payload.path)
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    result = await _run_file_op(item, command)
    return {"matches": (result.stdout or "").splitlines(), "truncated": result.truncated}


@app.post("/workspaces/{workspace_id}/import")
async def import_files(
    workspace_id: str, payload: ImportRequest, authorization: str | None = Header(default=None)
):
    """Скачать файлы пользователя по презайнед-ссылкам и положить внутрь песочницы.

    ⚠️ Ответ ПОФАЙЛОВЫЙ: один непринятый файл не отменяет остальные, но и не исчезает из
    ответа. Молча укоротившийся список выглядел бы как «файлов столько и было».
    """
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure

    results, total = [], 0
    for entry in plan(payload.files):
        try:
            if total >= MAX_TOTAL_BYTES:
                raise ImportRefused("суммарный потолок импорта исчерпан")
            data = await fetch(entry["url"])
            total += len(data)
            command = import_command(item.policy.root, entry["name"], data)
        except ImportRefused as exc:
            results.append({"name": entry["name"], "imported": False, "reason": str(exc)})
            continue
        result = await _run_file_op(item, command)
        ok = "__OK__" in (result.stdout or "")
        if ok:
            item.imported.add(entry["name"])
        results.append(
            {
                "name": entry["name"],
                "imported": ok,
                **({} if ok else {"reason": (result.stderr or "запись не удалась")[:200]}),
            }
        )
    return {"files": results, "imported": sum(1 for r in results if r["imported"])}


@app.post("/workspaces/{workspace_id}/artifacts")
async def list_artifacts(
    workspace_id: str, payload: OwnerRequest, authorization: str | None = Header(default=None)
):
    """Что агент создал внутри песочницы — чтобы backend отдал это пользователю.

    🔴 Импортированное СЮДА НЕ ВХОДИТ: вернуть человеку его же файл значит сообщить, что
    агент его создал. Песочница помнит, что мы в неё положили.
    """
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    result = await _run_file_op(item, artifacts_command(item.policy.root))
    files = parse_artifacts(result.stdout, item.policy.root, item.imported)
    return {"artifacts": files, "truncated": result.truncated}


@app.post("/workspaces/{workspace_id}/files/download")
async def download_file(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    """Содержимое файла КАК ЕСТЬ, в base64 — чтобы backend положил его в хранилище.

    🔴 Отдельно от `files/read`: тот отдаёт ТЕКСТ и разбирает байты как utf-8 с заменой
    битых. Для `.xlsx`, картинки или архива это порча, а не неточность — отданный
    пользователю файл просто не откроется.
    """
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        command = download_command(item.policy.root, payload.path)
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    result = await registry.exec_raw(item, command, max_output_chars=MAX_DOWNLOAD_BYTES * 2)
    try:
        content, truncated = parse_download(result.stdout)
    except FileNotFoundError:
        return _error("not_found", f"файла {payload.path!r} нет", 404)
    if truncated:
        # ⚠️ Обрезанный АРТЕФАКТ отдавать нельзя: неполный файл выглядит как целый и
        # ломается у пользователя. Отказ честнее половины.
        return _error("request_too_large", f"файл больше {MAX_DOWNLOAD_BYTES} байт", 413)
    return {"path": payload.path, "content_b64": content}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "driver": registry.driver_name if registry else DRIVER,
        "drivers_available": driver_names(),
        "workspaces": registry.count() if registry else 0,
        "contract": {
            "create_response_fields": sorted(CREATE_RESPONSE_FIELDS),
            "exec_response_fields": sorted(EXEC_RESPONSE_FIELDS),
            "error_codes": sorted(ERROR_CODES),
        },
    }


@app.on_event("startup")
async def _startup() -> None:
    global registry
    registry = WorkspaceRegistry(build_driver(DRIVER))
    # ⚠️ Уборщик — фоновой задачей приложения, а не cron'ом снаружи: контейнеры принадлежат
    # ЭТОМУ процессу, и внешний уборщик не знал бы, чьи они.
    asyncio.create_task(registry.reap_forever())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
