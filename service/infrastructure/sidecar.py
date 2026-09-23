"""Общая база клиента сайдкара: один способ звонить соседу.

До этого модуля каждый клиент решал одни и те же вопросы по-своему — и расхождения были
не стилистические, а поведенческие:

* таймаут брался из четырёх разных источников (конфиг, конфиг с хардкод-фолбэком,
  модульная константа, литерал в вызове), и у одного и того же сервиса оказывался
  разным у разных вызывающих;
* на `>=400` было ПЯТЬ разных исходов: пустое значение, значение-ошибка, `RuntimeError`,
  `HTTPException`, доменное исключение;
* транспортный сбой у одного клиента гасился, у другого улетал наверх — причём у
  ОДНОГО И ТОГО ЖЕ метода HTTP-ошибка была мягкой, а сетевая жёсткой;
* сквозного идентификатора не слал никто, поэтому собрать историю одного сообщения из
  логов разных сервисов было нельзя в принципе.

Здесь это сведено к одному поведению. Клиент наследника пишет только «что дёрнуть и что
вернуть», всё остальное — общее.

⚠️ О ДУБЛИРОВАНИИ. Такой же модуль понадобится backend'у: он тоже клиент сайдкаров.
Общего пакета для этого заводить НЕ будем — от него ушли осознанно (изменение контракта
не должно требовать согласованного релиза двух сервисов). Копия у второй стороны и страж
паритета — тот же приём, что уже применён к контракту `/run`.
"""

from __future__ import annotations

import logging
import re
import time
from contextvars import ContextVar
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Сквозной идентификатор запроса. ContextVar, а не аргумент: клиентов зовут из глубины
# доменного кода, и протаскивать идентификатор через каждую сигнатуру значило бы менять
# половину функций ради одной строки в логе — так его просто не стали бы носить.
_CORRELATION_ID: ContextVar[str | None] = ContextVar("gpthub_correlation_id", default=None)

CORRELATION_HEADER = "X-Correlation-Id"


def set_correlation_id(value: str | None) -> None:
    _CORRELATION_ID.set((value or "").strip() or None)


def get_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


class SidecarError(Exception):
    """Базовый отказ соседнего сервиса. Несёт машинный код, а не только текст."""

    def __init__(self, service: str, code: str, detail: str = "") -> None:
        del detail
        super().__init__(f"{service}: {code}")
        self.service = service
        self.code = code
        # Compatibility attribute. Raw HTTP bodies and exception text are never kept.
        self.detail = ""


class SidecarUnavailable(SidecarError):
    """Сосед не ответил или ответил 5xx. Наша сторона не виновата — деградируем."""


class SidecarTimeout(SidecarError):
    """Не уложились в срок: наш таймаут либо серверный дедлайн (504)."""


class SidecarBadRequest(SidecarError):
    """Виноват ВЫЗЫВАЮЩИЙ: 4xx.

    Отделено от `SidecarUnavailable` намеренно. «Файл такого формата не поддержан» —
    это то, что вызывающий (в том числе модель) может исправить сам, а «сервис лежит» —
    нет. Свести их в один тип значило бы отвечать пользователю «сервис недоступен» там,
    где достаточно было приложить другой файл.
    """


class SidecarClient:
    """База: таймаут из конфига, единая обработка ошибок, корреляция, телеметрия.

    Ретраев здесь НЕТ по умолчанию и это осознанно: почти все межсервисные вызовы в
    проекте неидемпотентны (запуск прогона, списание, генерация), и «на всякий случай»
    повторить их означало бы удвоить работу и деньги. Идемпотентному GET наследник может
    включить повтор явно.
    """

    def __init__(
        self,
        *,
        service: str,
        base_url: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.service = service
        self._base = (base_url or "").rstrip("/")
        self._timeout = float(timeout)
        # `transport` — для тестов (httpx.MockTransport), как это уже сделано у клиентов
        # ldr и memos. Без него тест был бы вынужден ПОВТОРИТЬ логику клиента у себя и
        # проверял бы собственную копию, а не рабочий код.
        self._transport = transport
        self._log = logging.getLogger(f"service.sidecar.{service}")

    @property
    def available(self) -> bool:
        return bool(self._base)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        cid = get_correlation_id()
        if cid:
            headers[CORRELATION_HEADER] = cid
        return headers

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        _raw_response: bool = False,
    ) -> Any:
        """Один вызов соседа. Успех → dict; отказ → исключение из таксономии выше.

        ⚠️ Отказ ВСЕГДА исключение, а не пустое значение. Fail-open («вернём {}») —
        главный источник немых поломок: вызывающий получает пустоту, принимает её за
        «данных нет» и идёт дальше. Решение деградировать принимает ВЫЗЫВАЮЩИЙ, явно
        поймав исключение, а не клиент за него.
        """
        if not self.available:
            raise SidecarUnavailable(self.service, "not_configured")

        url = f"{self._base}{path}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=timeout or self._timeout, transport=self._transport
            ) as client:
                resp = await client.request(
                    method,
                    url,
                    json=json_body,
                    content=content,
                    params=params,
                    headers=self._headers(headers),
                )
        except httpx.TimeoutException:
            raise SidecarTimeout(self.service, "timeout") from None
        except httpx.HTTPError:
            raise SidecarUnavailable(self.service, "transport_error") from None

        elapsed_ms = (time.perf_counter() - started) * 1000
        if resp.status_code >= 400:
            code, detail = self._read_error(resp)
            self._log.warning(
                "%s %s → HTTP %s (%s) за %.0fмс", method, path, resp.status_code, code, elapsed_ms
            )
            raise self._classify(resp.status_code, code, detail)

        self._log.debug("%s %s → %s за %.0fмс", method, path, resp.status_code, elapsed_ms)
        if _raw_response:
            return resp.content
        body = resp.json()
        return body if isinstance(body, dict) else {"result": body}

    async def request_bytes(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        """Same transport/error contract as ``request_json``, with a binary success body."""
        body = await self.request_json(
            method,
            path,
            json_body=json_body,
            content=content,
            params=params,
            headers=headers,
            timeout=timeout,
            _raw_response=True,
        )
        return bytes(body)

    def _classify(self, status: int, code: str, detail: str) -> SidecarError:
        """HTTP-код → тип отказа. Чей это сбой — вызывающего, сервиса или срока."""
        if status == 504:
            # Серверный дедлайн: сосед сам решил, что не успевает.
            return SidecarTimeout(self.service, code or "query_timeout", detail)
        if 400 <= status < 500:
            return SidecarBadRequest(self.service, code or f"http_{status}", detail)
        return SidecarUnavailable(self.service, code or f"http_{status}", detail)

    @staticmethod
    def _read_error(resp: httpx.Response) -> tuple[str, str]:
        """Read only a bounded machine code; never retain the response body."""
        try:
            body = resp.json()
        except Exception:
            return "", ""
        if isinstance(body, dict):
            raw = str(body.get("error") or "").strip().lower()
            code = raw if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", raw) else ""
            return code, ""
        return "", ""
