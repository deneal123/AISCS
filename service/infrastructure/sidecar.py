"""Общая база клиента сайдкара: один способ звонить соседу.

⚠️ ЭТО ВТОРАЯ КОПИЯ. Первая живёт в `agents/service/infrastructure/sidecar.py`. Общего
пакета не заводим осознанно — тем же решением, что и по контракту `/run`: он означал бы,
что правка требует согласованного релиза двух сервисов. Копии независимы, а расходиться
им незачем: это ~150 строк на голом httpx без доменной логики.

Что она устраняет (по инвентарю ВСЕХ 18 клиентов backend):

* таймаут брался из ЧЕТЫРЁХ источников — конфиг, конфиг с хардкод-фолбэком через `or`,
  модульная константа, литерал в вызове. У одного `graphify` — 900/60/30 у трёх мест
  ОДНОГО класса;
* на `>=400` было ПЯТЬ разных исходов: пустое значение, значение-ошибка, `RuntimeError`,
  `HTTPException`, доменное исключение;
* fail-open по умолчанию: клиент возвращал пустоту, а вызывающий принимал её за «данных
  нет» и шёл дальше;
* корреляция не пробрасывалась никем.

Отличие от копии в agents ровно одно: идентификатор берётся из уже существующего
`shared/observability/context`, а не из своего ContextVar — в backend он выставляется
воркером на входе в задачу.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AsyncExitStack, aclosing, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from service.shared.observability.context import get_correlation_id

logger = logging.getLogger(__name__)

CORRELATION_HEADER = "X-Correlation-Id"
_DIAGNOSTIC_COMPONENTS = frozenset({"agents", "agents-v1", "graphify", "opendataloader", "whisper"})


class SidecarError(Exception):
    """Базовый отказ соседнего сервиса. Несёт машинный код, а не только текст."""

    def __init__(self, service: str, code: str, detail: str = "") -> None:
        super().__init__(f"{service}: {code}{f' — {detail}' if detail else ''}")
        self.service = service
        self.code = code
        self.detail = detail


class SidecarUnavailable(SidecarError):
    """Сосед не ответил или ответил 5xx. Наша сторона не виновата — деградируем."""


class SidecarTimeout(SidecarError):
    """Не уложились в срок: наш таймаут либо серверный дедлайн (504)."""


class SidecarBadRequest(SidecarError):
    """Виноват ВЫЗЫВАЮЩИЙ: 4xx.

    Отделено намеренно. «Файл такого формата не поддержан» вызывающий может исправить
    сам, «сервис лежит» — нет. Свести их в один тип значило бы отвечать пользователю
    «сервис недоступен» там, где достаточно приложить другой файл.
    """


@dataclass(frozen=True, slots=True)
class BinarySidecarResponse:
    headers: httpx.Headers = field(repr=False)
    chunks: AsyncIterator[bytes] = field(repr=False)


class SidecarClient:
    """База: таймаут из конфига, единая обработка ошибок, корреляция, телеметрия.

    Ретраев по умолчанию НЕТ: почти все межсервисные вызовы неидемпотентны (прогон,
    списание, генерация), и «на всякий случай повторить» удвоило бы работу и деньги.
    """

    def __init__(
        self,
        *,
        service: str,
        base_url: str,
        timeout: float,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.service = service
        self._base = (base_url or "").rstrip("/")
        self._timeout = float(timeout)
        self._key = str(api_key or "")
        # `transport` — для тестов (httpx.MockTransport). Без него тест был бы вынужден
        # ПОВТОРИТЬ логику клиента у себя и проверял бы собственную копию.
        self._transport = transport
        # Remote or extension-provided service names are not diagnostic labels.
        self._component = service if service in _DIAGNOSTIC_COMPONENTS else "other"
        self._log = logging.getLogger(f"service.sidecar.{self._component}")

    @property
    def available(self) -> bool:
        return bool(self._base)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        cid = get_correlation_id()
        if cid:
            # Пустой не шлём: заголовок-прочерк врал бы о наличии трассы.
            headers[CORRELATION_HEADER] = cid
        return headers

    async def upload_binary_json(
        self,
        path: str,
        *,
        content: AsyncIterator[bytes] | bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> dict:
        """One private upload, bounded JSON reply; no redirects/retry/raw errors."""
        if not self.available:
            raise SidecarUnavailable(self.service, "not_configured")
        try:
            async with (
                httpx.AsyncClient(
                    timeout=timeout,
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "POST",
                    f"{self._base}{path}",
                    content=content,
                    headers=self._headers({**headers, "Accept-Encoding": "identity"}),
                ) as response,
            ):
                if (
                    response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                    or response.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise SidecarUnavailable(self.service, "protocol")
                declared = response.headers.get("content-length")
                if declared is not None and (
                    not declared.isascii()
                    or not declared.isdecimal()
                    or not 0 < int(declared) <= 16384
                ):
                    raise SidecarUnavailable(self.service, "protocol")
                body = bytearray()
                stream = cast(AsyncGenerator[bytes], response.aiter_raw(4096))
                async with aclosing(stream) as chunks:
                    async for chunk in chunks:
                        if len(body) + len(chunk) > 16384:
                            raise SidecarUnavailable(self.service, "protocol")
                        body.extend(chunk)
                if declared is not None and len(body) != int(declared):
                    raise SidecarUnavailable(self.service, "protocol")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise SidecarUnavailable(self.service, "protocol")
                if (
                    response.status_code == 200
                    and response.headers.get("cache-control") != "no-store"
                ):
                    raise SidecarUnavailable(self.service, "protocol")
                if response.status_code != 200:
                    code = value.get("error")
                    if (
                        response.status_code < 400
                        or not isinstance(code, str)
                        or not (
                            code.isascii() and len(code) <= 64 and code.replace("_", "").isalnum()
                        )
                    ):
                        raise SidecarUnavailable(self.service, "protocol")
                    raise self._classify(response.status_code, code, "")
                return value
        except httpx.TimeoutException:
            raise SidecarTimeout(self.service, "timeout") from None
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise SidecarUnavailable(self.service, "protocol") from None

    @asynccontextmanager
    async def request_binary(
        self, path: str, *, json_body: Any, max_bytes: int, timeout: float
    ) -> AsyncIterator[BinarySidecarResponse]:
        """Private bounded POST stream. No buffering, redirects, retries or raw errors."""
        if type(max_bytes) is not int or not 0 < max_bytes < 2**31:
            raise ValueError("invalid_binary_limit")
        async with AsyncExitStack() as resources:
            try:
                client = await resources.enter_async_context(
                    httpx.AsyncClient(
                        timeout=timeout,
                        transport=self._transport,
                        follow_redirects=False,
                    )
                )
                response = await resources.enter_async_context(
                    client.stream(
                        "POST",
                        f"{self._base}{path}",
                        json=json_body,
                        headers=self._headers({"Accept-Encoding": "identity"}),
                    )
                )
                if not 200 <= response.status_code < 300:
                    cls = (
                        SidecarBadRequest
                        if 400 <= response.status_code < 500
                        else SidecarUnavailable
                    )
                    raise cls(self.service, f"http_{response.status_code}")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise SidecarUnavailable(self.service, "protocol")
            except (httpx.TimeoutException, TimeoutError):
                raise SidecarTimeout(self.service, "timeout") from None
            except httpx.HTTPError:
                raise SidecarUnavailable(self.service, "protocol") from None

            async def chunks():
                size = 0
                try:
                    async with aclosing(response.aiter_raw(65536)) as source:
                        async for chunk in source:
                            size += len(chunk)
                            if size > max_bytes:
                                raise SidecarUnavailable(self.service, "binary_limit")
                            yield chunk
                except (httpx.TimeoutException, TimeoutError):
                    raise SidecarTimeout(self.service, "timeout") from None
                except httpx.HTTPError:
                    raise SidecarUnavailable(self.service, "protocol") from None

            # Consumer/storage failures are outside the transport error mapping.
            iterator = chunks()
            resources.push_async_callback(iterator.aclose)
            yield BinarySidecarResponse(response.headers, iterator)

    async def request_ndjson(
        self,
        method: str,
        path: str,
        *,
        json_body: Any,
        max_frame_bytes: int = 4 * 1024 * 1024,
        max_frames: int = 256,
    ) -> AsyncGenerator[dict]:
        """Bounded private stream; no retries, redirects, response-body diagnostics."""
        if not self.available:
            raise SidecarUnavailable(self.service, "not_configured")
        if not 1 <= max_frame_bytes <= 4 * 1024 * 1024 or not 1 <= max_frames <= 256:
            raise SidecarBadRequest(self.service, "invalid")
        try:
            async with (
                asyncio.timeout(self._timeout),
                httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    method, f"{self._base}{path}", json=json_body, headers=self._headers()
                ) as response,
            ):
                if response.status_code != 200:
                    failure = (
                        SidecarBadRequest if response.status_code < 500 else SidecarUnavailable
                    )
                    raise failure(self.service, "unavailable")
                if (
                    response.headers.get("content-type", "").split(";", 1)[0]
                    != "application/x-ndjson"
                ):
                    raise SidecarUnavailable(self.service, "protocol")
                buffer = bytearray()
                count = 0
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    while b"\n" in buffer:
                        line, _, remainder = buffer.partition(b"\n")
                        buffer = bytearray(remainder)
                        count += 1
                        if not line or len(line) > max_frame_bytes or count > max_frames:
                            raise SidecarUnavailable(self.service, "protocol")
                        frame = json.loads(line)
                        if not isinstance(frame, dict):
                            raise SidecarUnavailable(self.service, "protocol")
                        yield frame
                    if len(buffer) > max_frame_bytes:
                        raise SidecarUnavailable(self.service, "protocol")
                if buffer:
                    raise SidecarUnavailable(self.service, "protocol")
        except (TimeoutError, httpx.TimeoutException):
            raise SidecarTimeout(self.service, "timeout") from None
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise SidecarUnavailable(self.service, "protocol") from None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Один вызов соседа. Успех → Response; отказ → исключение из таксономии выше.

        ⚠️ Отказ ВСЕГДА исключение, а не пустое значение. Решение деградировать
        принимает ВЫЗЫВАЮЩИЙ, явно поймав исключение, — не клиент за него.
        """
        if not self.available:
            raise SidecarUnavailable(self.service, "not_configured", "адрес сервиса не задан")

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=timeout or self._timeout,
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                resp = await client.request(
                    method,
                    f"{self._base}{path}",
                    json=json_body,
                    content=content,
                    params=params,
                    headers=self._headers(headers),
                )
        except httpx.TimeoutException as exc:
            raise SidecarTimeout(self.service, "timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise SidecarUnavailable(self.service, "transport_error", str(exc)) from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        if resp.status_code >= 400:
            code, detail = self._read_error(resp)
            failure = (
                "timeout"
                if resp.status_code == 504
                else "invalid"
                if resp.status_code < 500
                else "unavailable"
            )
            self._log.warning(
                "Sidecar request failed: %s (HTTP %s, %.0fms)",
                failure,
                resp.status_code,
                elapsed_ms,
                extra={"component": self._component, "failure_code": failure},
            )
            raise self._classify(resp.status_code, code, detail)

        self._log.debug(
            "Sidecar request completed (HTTP %s, %.0fms)",
            resp.status_code,
            elapsed_ms,
            extra={"component": self._component},
        )
        return resp

    async def request_json(self, method: str, path: str, **kw: Any) -> dict:
        resp = await self.request(method, path, **kw)
        body = resp.json()
        return body if isinstance(body, dict) else {"result": body}

    def _classify(self, status: int, code: str, detail: str) -> SidecarError:
        """HTTP-код → тип отказа. Чей это сбой — вызывающего, сервиса или срока."""
        if status == 504:
            # Серверный дедлайн: сосед сам решил, что не успевает.
            return SidecarTimeout(self.service, code or "server_deadline", detail)
        if 400 <= status < 500:
            return SidecarBadRequest(self.service, code or f"http_{status}", detail)
        return SidecarUnavailable(self.service, code or f"http_{status}", detail)

    @staticmethod
    def _read_error(resp: httpx.Response) -> tuple[str, str]:
        """Разобрать единую форму ошибки `{"error", "detail"}`.

        Сервис, ещё не приведённый к регламенту, вернёт что-то своё — тогда берём тело
        текстом. Это не повод падать: раскатка идёт по сервисам, а не одномоментно.
        """
        try:
            body = resp.json()
        except Exception:
            return "", resp.text[:300]
        if isinstance(body, dict):
            return str(body.get("error") or ""), str(body.get("detail") or "")[:300]
        return "", str(body)[:300]
