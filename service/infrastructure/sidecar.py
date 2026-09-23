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

import logging
import time
from typing import Any

import httpx

from service.shared.observability.context import get_correlation_id

logger = logging.getLogger(__name__)

CORRELATION_HEADER = "X-Correlation-Id"


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
        self._log = logging.getLogger(f"service.sidecar.{service}")

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
                timeout=timeout or self._timeout, transport=self._transport
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
            self._log.warning(
                "%s %s → HTTP %s (%s) за %.0fмс", method, path, resp.status_code, code, elapsed_ms
            )
            raise self._classify(resp.status_code, code, detail)

        self._log.debug("%s %s → %s за %.0fмс", method, path, resp.status_code, elapsed_ms)
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
