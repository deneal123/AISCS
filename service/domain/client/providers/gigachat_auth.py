"""OAuth2-авторизация GigaChat (Сбер) для OpenAI-совместимого клиента.

GigaChat принимает Bearer access_token, который выдаётся OAuth-эндпоинтом по
Authorization-ключу (base64 от client_id:client_secret) и живёт ~30 минут.
Токен нужно периодически обновлять. ``GigaChatAuth`` подставляет свежий токен в
каждый исходящий запрос httpx, перекрывая статичный ключ, который ставит SDK.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# Если OAuth не вернул expires_at — считаем токен живым ~25 минут.
_FALLBACK_TTL_SEC = 25 * 60


class GigaChatTokenManager:
    """Потокобезопасный кэш access_token с авто-обновлением до протухания."""

    def __init__(
        self,
        *,
        authorization_key: str,
        scope: str,
        oauth_url: str,
        verify: Any,
        timeout: float,
        skew_sec: int = 60,
        proxy_url: str = "",
    ) -> None:
        self._authorization_key = (authorization_key or "").strip()
        self._scope = (scope or "GIGACHAT_API_PERS").strip()
        self._oauth_url = (oauth_url or DEFAULT_OAUTH_URL).strip()
        self._verify = verify
        self._timeout = timeout
        self._skew_ms = max(0, int(skew_sec)) * 1000
        self._proxy_url = proxy_url or ""
        self._access_token: str | None = None
        self._expires_at_ms: int = 0
        # Лок создаём ЛЕНИВО и пере-привязываем к текущему event loop. Менеджер —
        # модульный синглтон, а celery крутит НОВЫЙ loop на каждую задачу: лок,
        # созданный в __init__, привязался бы к первому loop, и `async with` на
        # втором запросе воркера падал бы `RuntimeError: bound to a different event
        # loop` (тот же класс бага, что уже обходили sync-Redis в circuit_breaker).
        # В процессе одновременно активен один loop (loop-per-task), поэтому
        # пересоздание лока при смене loop безопасно.
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    def _is_fresh(self) -> bool:
        if not self._access_token:
            return False
        now_ms = int(time.time() * 1000)
        return now_ms < (self._expires_at_ms - self._skew_ms)

    def invalidate(self) -> None:
        """Сбросить токен — следующий запрос форсирует обновление (напр. после 401)."""
        self._access_token = None
        self._expires_at_ms = 0

    async def get_token(self, *, force: bool = False) -> str:
        if not self._authorization_key:
            raise RuntimeError(
                "GigaChat is not configured: missing AGENTS__GIGACHAT_AUTHORIZATION_KEY"
            )
        if not force and self._is_fresh():
            return self._access_token  # type: ignore[return-value]
        async with self._get_lock():
            # double-checked: другой корутин мог уже обновить токен
            if not force and self._is_fresh():
                return self._access_token  # type: ignore[return-value]
            await self._refresh()
            return self._access_token  # type: ignore[return-value]

    async def _refresh(self) -> None:
        headers = {
            "Authorization": f"Basic {self._authorization_key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        client_kwargs: dict[str, Any] = {"verify": self._verify, "timeout": self._timeout}
        if self._proxy_url:
            client_kwargs["proxy"] = self._proxy_url
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(self._oauth_url, headers=headers, data={"scope": self._scope})
            resp.raise_for_status()
            payload = resp.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("GigaChat OAuth response has no access_token")
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)) and expires_at > 0:
            self._expires_at_ms = int(expires_at)
        else:
            self._expires_at_ms = int(time.time() * 1000) + _FALLBACK_TTL_SEC * 1000
        self._access_token = token
        logger.info("GigaChat access token refreshed (scope=%s)", self._scope)


class GigaChatAuth(httpx.Auth):
    """httpx-auth: ставит свежий Bearer-токен на каждый запрос; на 401 — один повтор."""

    def __init__(self, token_manager: GigaChatTokenManager) -> None:
        self._tm = token_manager

    async def async_auth_flow(self, request: httpx.Request):
        token = await self._tm.get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            # Токен мог протухнуть/быть отозван — обновляем и повторяем один раз.
            self._tm.invalidate()
            token = await self._tm.get_token(force=True)
            request.headers["Authorization"] = f"Bearer {token}"
            yield request
