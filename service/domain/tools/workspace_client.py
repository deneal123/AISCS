"""Клиент сайдкара workspace: файловая песочница агента.

⚠️ Слой агентов НЕ ЗНАЕТ про docker и знать не должен. Он умеет ровно одно: сказать «прочитай
файл» тому сервису, которому отдан сокет демона. Граница проходит по HTTP, и это её главное
свойство — по эту сторону нет ни одного способа обратиться к рантайму напрямую.

🔴 Ссылка на песочницу приходит ОКРУЖЕНИЕМ ПРОГОНА (`context.workspace_ref`), а не из
аргументов, которые придумывает модель. Иначе модель называла бы чужой `workspace_id` — а
токен владения как раз и существует, чтобы этого не было; принимать его от модели значило бы
отдать ей ключ.
"""

from __future__ import annotations

import hashlib
import logging
from functools import partial
from typing import Any

import httpx

from service.domain.integration_failure import (
    IntegrationFailure,
    IntegrationFailureCode,
    IntegrationSource,
    StatusFamily,
    status_family,
)
from service.domain.run_context import current_execution

logger = logging.getLogger(__name__)


class WorkspaceUnavailable(IntegrationFailure):
    """Compatibility name for the typed workspace integration failure."""

    def __init__(
        self,
        code: IntegrationFailureCode | str = IntegrationFailureCode.UNAVAILABLE,
        *,
        retryable: bool = False,
        family: StatusFamily = StatusFamily.NONE,
    ) -> None:
        normalized = (
            code if isinstance(code, IntegrationFailureCode) else IntegrationFailureCode.INTERNAL
        )
        super().__init__(IntegrationSource.WORKSPACE, normalized, retryable, family)


_REVISIONED_MUTATIONS = frozenset(
    {
        "files/write",
        "revert",
        "documents",
        "documents/profile",
        "documents/builds",
        "documents/source",
        "documents/authoring/checkpoint",
        "documents/vendor/activate",
    }
)


def _settings() -> tuple[str, float, bool]:
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    enabled = bool(
        runtime_settings.get_agents("workspace_enabled", config.agents.workspace_enabled)
    )
    # ⚠️ Адрес — ИЗ КОНФИГА, а не через overlay: это координата развёртывания, а не ручка
    # админа. Ключ, объявленный в реестре админки, обязан быть там крутибельным; адрес
    # соседнего контейнера крутить из панели незачем — и офлайн-страж справедливо требует
    # объявить всё, что читается через снимок.
    base = str(config.agents.workspace_url or "").rstrip("/")
    timeout = float(
        runtime_settings.get_agents("workspace_timeout_sec", config.agents.workspace_timeout_sec)
        or 120.0
    )
    return base, timeout, enabled


def _credentials(ref: Any) -> tuple[str, str, str]:
    """`workspace_id`, токен владения и идентификатор пользователя из ссылки прогона."""
    data = ref if isinstance(ref, dict) else {}
    workspace_id = str(data.get("workspace_id") or "").strip()
    token = str(data.get("token") or "").strip()
    user_id = str(data.get("user_id") or "").strip()
    if not workspace_id or not token:
        raise WorkspaceUnavailable(IntegrationFailureCode.INVALID)
    return workspace_id, token, user_id


def _raise_http_failure(path: str, status_code: int) -> None:
    del path
    code, retryable = {
        404: (IntegrationFailureCode.EXPIRED, False),
        409: (IntegrationFailureCode.CONFLICT, True),
        410: (IntegrationFailureCode.EXPIRED, False),
        422: (IntegrationFailureCode.INVALID, False),
        423: (IntegrationFailureCode.CONFLICT, True),
        503: (IntegrationFailureCode.UNAVAILABLE, True),
    }.get(status_code, (IntegrationFailureCode.REMOTE, status_code >= 500))
    if code is IntegrationFailureCode.CONFLICT:
        execution = current_execution()
        if execution is not None:
            execution.workspace.invalidate(require_read=True)
    logger.warning("workspace integration failed code=%s", code.value)
    raise WorkspaceUnavailable(code, retryable=retryable, family=status_family(status_code))


def _json_response(response: httpx.Response, path: str) -> dict:
    if response.status_code >= 400:
        _raise_http_failure(path, response.status_code)
    try:
        return response.json() or {}
    except Exception:  # noqa: BLE001
        raise WorkspaceUnavailable(IntegrationFailureCode.PROTOCOL) from None


async def _send_workspace_request(
    client: httpx.AsyncClient,
    *,
    base: str,
    workspace_id: str,
    user_id: str,
    token: str,
    path: str,
    url: str,
    headers: dict[str, str],
    body: dict,
    capability: str,
) -> dict:
    execution = current_execution()
    session = execution.workspace if execution is not None else None
    mutation = bool(capability and path in _REVISIONED_MUTATIONS)
    if mutation and session is not None and session.requires_read:
        raise WorkspaceUnavailable(IntegrationFailureCode.CONFLICT, retryable=True)
    if mutation and not body.get("expected_revision"):
        revision = session.revision if session is not None and session.valid else None
        if not revision:
            view = _json_response(
                await client.post(
                    f"{base}/workspaces/{workspace_id}/view",
                    json={
                        "user_id": user_id,
                        "token": token,
                        "coordination_capability": capability,
                    },
                    headers=headers,
                ),
                "view",
            )
            revision = str(view.get("revision") or "").strip()
            if not revision:
                raise WorkspaceUnavailable(IntegrationFailureCode.PROTOCOL)
            if session is not None:
                session.observe(revision)
        body["expected_revision"] = revision
    elif mutation and session is not None:
        session.observe(body.get("expected_revision"))

    result = _json_response(await client.post(url, json=body, headers=headers), path)
    if session is not None:
        session.observe(result.get("revision"))
    return result


async def call(ref: Any, path: str, payload: dict) -> dict:
    """Один вызов сайдкара. Ошибку превращаем в исключение с ЧЕЛОВЕЧЕСКИМ текстом.

    ⚠️ Текст уедет МОДЕЛИ, а не в лог: она должна суметь сказать пользователю, что именно не
    получилось, вместо того чтобы выдумать содержимое файла.
    """
    from service.settings import config

    base, timeout, enabled = _settings()
    if not enabled:
        raise WorkspaceUnavailable(IntegrationFailureCode.POLICY)
    if not base:
        raise WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE)
    workspace_id, token, user_id = _credentials(ref)

    from service.shared import deadline

    key = str(getattr(config.agents, "workspace_api_key", "") or "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    # The capability is supplied by backend execution context, never by model
    # arguments.  It remains opaque to tools and is not put in trace metadata.
    capability = str((ref if isinstance(ref, dict) else {}).get("coordination_capability") or "")
    body = {
        "user_id": user_id,
        "token": token,
        **({"coordination_capability": capability} if capability else {}),
        **payload,
    }
    url = f"{base}/workspaces/{workspace_id}/{path.lstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=deadline.clamp(timeout)) as client:
            execution = current_execution()
            send = partial(
                _send_workspace_request,
                client,
                base=base,
                workspace_id=workspace_id,
                user_id=user_id,
                token=token,
                path=path,
                url=url,
                headers=headers,
                body=body,
                capability=capability,
            )
            if capability and path in _REVISIONED_MUTATIONS and execution is not None:
                async with execution.workspace.lock():
                    return await send()
            return await send()
    except WorkspaceUnavailable:
        raise
    except httpx.TimeoutException:
        logger.warning("workspace integration failed code=timeout")
        raise WorkspaceUnavailable(
            IntegrationFailureCode.TIMEOUT,
            retryable=True,
            family=StatusFamily.TRANSPORT,
        ) from None
    except httpx.TransportError:
        logger.warning("workspace integration failed code=transport")
        raise WorkspaceUnavailable(
            IntegrationFailureCode.TRANSPORT,
            retryable=True,
            family=StatusFamily.TRANSPORT,
        ) from None
    except Exception:  # noqa: BLE001
        logger.warning("workspace integration failed code=internal")
        raise WorkspaceUnavailable(IntegrationFailureCode.INTERNAL) from None


async def download_binary(
    ref: Any,
    path: str,
    *,
    max_bytes: int,
) -> tuple[bytes, dict[str, str]]:
    """Read one bounded private artifact without exposing its URL or credentials."""

    from service.settings import config
    from service.shared import deadline

    base, timeout, enabled = _settings()
    if not enabled or not base:
        raise WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE)
    workspace_id, token, user_id = _credentials(ref)
    key = str(getattr(config.agents, "workspace_api_key", "") or "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    capability = str((ref if isinstance(ref, dict) else {}).get("coordination_capability") or "")
    body = {
        "user_id": user_id,
        "token": token,
        **({"coordination_capability": capability} if capability else {}),
    }
    url = f"{base}/workspaces/{workspace_id}/{path.lstrip('/')}"
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    size = 0
    try:
        async with httpx.AsyncClient(timeout=deadline.clamp(timeout)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code >= 400:
                    _raise_http_failure(path, response.status_code)
                async for chunk in response.aiter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise WorkspaceUnavailable(IntegrationFailureCode.INVALID)
                    digest.update(chunk)
                    chunks.append(chunk)
                expected_size = response.headers.get("content-length")
                expected_digest = response.headers.get("x-artifact-sha256", "").lower()
                if expected_size and int(expected_size) != size:
                    raise WorkspaceUnavailable(IntegrationFailureCode.PROTOCOL)
                if expected_digest and expected_digest != digest.hexdigest():
                    raise WorkspaceUnavailable(IntegrationFailureCode.PROTOCOL)
                safe_headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower().startswith("x-document-")
                    or key.lower() in {"x-artifact-sha256", "content-length"}
                }
                return b"".join(chunks), safe_headers
    except WorkspaceUnavailable:
        raise
    except (ValueError, httpx.DecodingError):
        raise WorkspaceUnavailable(IntegrationFailureCode.PROTOCOL) from None
    except httpx.TimeoutException:
        raise WorkspaceUnavailable(IntegrationFailureCode.TIMEOUT, retryable=True) from None
    except httpx.TransportError:
        raise WorkspaceUnavailable(IntegrationFailureCode.TRANSPORT, retryable=True) from None


async def list_artifacts(ref: Any) -> list[dict]:
    """Что агент создал внутри песочницы. Пусто — ничего или песочницы нет.

    ⚠️ Best-effort и БЕЗ исключений наружу: это отчёт в конце прогона, и уронить из-за него
    уже готовый ответ было бы худшим разменом. Не смогли спросить — пусто.
    """
    try:
        data = await call(ref, "artifacts", {})
    except WorkspaceUnavailable as exc:
        logger.warning("workspace artifacts unavailable code=%s", exc.reason_code)
        return []
    items = data.get("artifacts")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
