"""HTTP-клиент к микросервису local-deep-research (LDR).

Обёртка над REST API LDR (`:5000`) для использования зрелой агентной стратегии
`langgraph-agent` вместо нашего нативного `deep_research()`. Разворачивается как
отдельный сервис (см. docker/docker-compose.ldr.yaml), по образцу интеграции
MemOS.

Контракт LDR (сверять с docs/api-quickstart.md при обновлении LDR):
  - POST /auth/login            (form: username, password, csrf_token)
  - GET  /auth/csrf-token       -> {"csrf_token": ...}  (для X-CSRF-Token)
  - POST /api/start_research    {query, model, search_engines, iterations}
                                -> {"research_id"|"id": ..., "status": ...}
  - GET  /api/research/{id}/status -> {"status": ..., "progress": ...}
  - GET  /api/report/{id}       -> {"summary"|"report", "sources": [...]}
  - GET  /metrics/api/metrics/research/{id} -> токены (input/output/total)

Стратегия (`langgraph-agent`) и LLM-провайдер задаются глобально в настройках/env
самого LDR (см. compose), поэтому в payload не передаются — так безопаснее к
неизвестным полям API.

Разбор ответов намеренно ТОЛЕРАНТЕН к вариациям имён полей: точную схему уточнять
живым запросом при первой настройке (как для MemOS — доверяем коду, а не примеру).
Любая инфраструктурная проблема поднимает `LDRUnavailableError`, чтобы агент
откатился на нативный deep_research().
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)


_DONE_STATES = {"completed", "complete", "finished", "done", "success"}
_FAILED_STATES = {"failed", "error", "cancelled", "canceled", "suspended"}


class LDRUnavailableError(RuntimeError):
    """LDR недоступен/не настроен/сбой соединения → откат на нативный путь."""

    _ALLOWED_CODES = {"not_configured", "unavailable", "timeout", "protocol", "remote"}

    def __init__(self, reason_code: str = "unavailable") -> None:
        self.reason_code = reason_code if reason_code in self._ALLOWED_CODES else "unavailable"
        super().__init__(self.reason_code)


class LDRResearchFailed(LDRUnavailableError):
    """Исследование завершилось ошибкой на стороне LDR."""

    def __init__(self, reason_code: str = "remote") -> None:
        super().__init__(reason_code)


class LDRTimeout(LDRUnavailableError):
    """Дедлайн опроса исчерпан (research не успел завершиться)."""

    def __init__(self, reason_code: str = "timeout") -> None:
        super().__init__(reason_code)


def _strip_provider_prefix(model: str) -> str:
    """ "openrouter:openai/gpt-4o-mini" → "openai/gpt-4o-mini".

    LDR через наш gateway использует модель вида "<provider>:<model>". Для
    биллинга нужен чистый id модели (совпадение с прайс-реестром).
    """
    if isinstance(model, str) and ":" in model:
        head, _, rest = model.partition(":")
        if head and "/" not in head and rest:
            return rest
    return model


# Хвост отчёта LDR: он сам вклеивает разделы "Sources" и "Research Metrics".
# Мы формируем свой блок «Источники», поэтому LDR-хвост режем, чтобы не было
# дублей. Ищем первую строку-заголовок одного из этих разделов.
_REPORT_TAIL_RE = re.compile(
    r"(?im)^[ \t>]*(?:#{1,6}[ \t]*)?(?:\*\*)?[ \t]*"
    r"(?:sources|research\s+metrics|источники|список\s+источников)"
    r"[ \t]*(?:\*\*)?[ \t]*:?[ \t]*$"
)


def _strip_report_tail(text: str) -> str:
    if not text:
        return text
    m = _REPORT_TAIL_RE.search(text)
    return text[: m.start()].rstrip() if m else text


def _first(payload: Any, *keys: str) -> Any:
    """Первое не-None значение по списку возможных имён полей."""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


class LDRResearchClient:
    """Тонкий async-клиент к LDR с кэшированной сессией (cookie + CSRF)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        model: str | None = None,
        search_engines: str | None = None,
        strategy: str | None = None,
        iterations: int | None = None,
        timeout: float | None = None,
        poll_interval: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        raw_base = base_url if base_url is not None else config.agents.ldr_base_url
        self._base_url = (raw_base or "").rstrip("/")
        self._username = (username if username is not None else config.agents.ldr_username).strip()
        self._password = password if password is not None else config.agents.ldr_password
        raw_model = model if model is not None else config.agents.ldr_model
        self._model = raw_model or "openai/gpt-4o-mini"
        raw_engines = (
            search_engines if search_engines is not None else config.agents.ldr_search_engines
        )
        self._engines = [e.strip() for e in (raw_engines or "searxng").split(",") if e.strip()]
        if len(self._engines) > 1:
            # ⚠️ НЕ баг «CSV теряется»: у LDR `search_engine` — скалярное поле ОСНОВНОГО
            # движка, а множественность даёт стратегия `langgraph-agent`. Но настройка
            # выглядит списком, поэтому молчать нельзя.
            logger.warning(
                "ldr_search_engines содержит %d движков (%s) — как ОСНОВНОЙ уйдёт "
                "только первый (%s). Остальные не теряются: их подключает стратегия "
                "langgraph-agent из настроек самого LDR.",
                len(self._engines),
                ", ".join(self._engines),
                self._engines[0],
            )
        self._strategy = (strategy if strategy is not None else config.agents.ldr_strategy) or ""
        self._iterations = int(
            iterations if iterations is not None else config.agents.ldr_iterations
        )
        # ⚠️ Через overlay, а не из конфига напрямую. Оба ключа ОБЪЯВЛЕНЫ в админке
        # рядом с ldr_model и ldr_strategy, но читались в обход снимка: админ менял
        # таймаут исследования, значение сохранялось, а прогон шёл по-старому. Молча.
        # Ровно этот класс дефекта нашёл офлайн-страж ключей agents.*.
        self._timeout = float(
            timeout
            if timeout is not None
            else runtime_settings.get_agents("ldr_timeout_sec", config.agents.ldr_timeout_sec)
        )
        self._poll_interval = float(
            poll_interval
            if poll_interval is not None
            else runtime_settings.get_agents(
                "ldr_poll_interval_sec", config.agents.ldr_poll_interval_sec
            )
        )
        self._transport = transport  # httpx.MockTransport в тестах
        self._client: httpx.AsyncClient | None = None
        self._csrf: str | None = None
        # id прогона, который ИДЁТ прямо сейчас. Сбрасывается по завершении
        # (штатному или отменой) — см. `terminate` и `report`.
        self._active_research_id: str | None = None

    @property
    def available(self) -> bool:
        return bool(self._base_url and self._username and self._password)

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------------ session
    def _session(self) -> httpx.AsyncClient:
        # Один клиент на весь жизненный цикл — сохраняет cookie-сессию логина.
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None
                self._csrf = None
                self._active_research_id = None

    async def _ensure_session(self) -> None:
        """Логин по паролю + получение API-CSRF. Идемпотентно (кэш)."""
        if self._csrf:
            return
        if not self.available:
            raise LDRUnavailableError("not_configured")
        client = self._session()
        try:
            # 1) CSRF — из JSON-ручки, а НЕ парсингом страницы логина: регулярка по
            # разметке чужой формы привязывала нас к вёрстке апстрима, и смена шаблона
            # ломала бы аутентификацию под видом «LDR недоступен».
            tok = await client.get("/auth/csrf-token")
            login_csrf = _first(self._safe_json(tok), "csrf_token", "token")
            # 2) Логин формой (сам эндпоинт принимает form-data, это не изменилось).
            form = {"username": self._username, "password": self._password}
            if login_csrf:
                form["csrf_token"] = str(login_csrf)
            # Редирект НЕ следуем: на успехе LDR уводит на страницу веб-интерфейса,
            # которая нам не нужна. Сессия к этому моменту уже лежит в куке клиента,
            # так что 3xx — это успех, а не повод ходить ещё раз.
            resp = await client.post("/auth/login", data=form, follow_redirects=False)
            if resp.status_code >= 400:
                raise LDRUnavailableError("remote")
            # 3) API-CSRF для последующих запросов: после логина сессия другая, и
            # токен, взятый до него, для неё уже не годится.
            tok = await client.get("/auth/csrf-token")
            csrf = _first(self._safe_json(tok), "csrf_token", "token")
            if not csrf:
                raise LDRUnavailableError("protocol")
            self._csrf = str(csrf)
        except LDRUnavailableError:
            raise
        except Exception:  # network/parse boundary
            raise LDRUnavailableError("unavailable") from None

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {"data": data}

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._csrf:
            # flask-wtf принимает оба имени (WTF_CSRF_HEADERS) — шлём оба.
            h["X-CSRFToken"] = self._csrf
            h["X-CSRF-Token"] = self._csrf
        return h

    async def _get(self, path: str) -> dict[str, Any]:
        client = self._session()
        resp = await client.get(path, headers=self._headers())
        if resp.status_code == 401:
            self._csrf = None  # сессия протухла — перелогинимся выше по стеку
            raise LDRUnavailableError("unavailable")
        if resp.status_code >= 400:
            raise LDRUnavailableError("remote")
        return self._safe_json(resp)

    # ------------------------------------------------------------------ research
    async def start_research(self, query: str) -> str:
        await self._ensure_session()
        # search_engine — ОДИН основной движок, не список. Множественность даёт стратегия:
        # `langgraph-agent` регистрирует `search_<движок>` по всем доступным и выбирает
        # динамически, `source-based` работает ровно этим одним. Ключевой буст качества.
        payload: dict[str, Any] = {
            "query": query,
            "model": self._model,
            "search_engine": self._engines[0] if self._engines else "searxng",
            "iterations": self._iterations,
        }
        if self._strategy:
            payload["strategy"] = self._strategy
        client = self._session()
        try:
            resp = await client.post("/api/start_research", json=payload, headers=self._headers())
        except Exception:
            raise LDRUnavailableError("unavailable") from None
        if resp.status_code >= 400:
            raise LDRUnavailableError("remote")
        data = self._safe_json(resp)
        rid = _first(data, "research_id", "id", "researchId")
        if not rid:
            raise LDRUnavailableError("protocol")
        # Запоминаем на клиенте, чтобы отменить прогон, не протаскивая id через
        # весь стек агента: отмена приходит извне и в произвольный момент.
        self._active_research_id = str(rid)
        return str(rid)

    async def terminate(self) -> bool:
        """Остановить текущий прогон на стороне LDR. Best-effort, не поднимает.

        ⚠️ ЗАЧЕМ ЭТО ВООБЩЕ. Без отмены «стоп» у пользователя останавливал только
        НАС: мы переставали читать статус, а LDR продолжал исследование. Токены при
        этом жгутся через наш же шлюз `/v1`, который НЕ тарифицирует (биллинг идёт
        из `/metrics`, а их мы после отмены уже не заберём). Итог — провайдер
        списывает с нас, а мы не списываем ни с кого.

        Тонкость вызова: этот метод зовут из `finally` УЖЕ ОТМЕНЁННОЙ задачи. Пока
        отмену доставили однократно, обычный `await` доходит; но повторная отмена
        (шатдаун, добивающий задачи) убьёт сам запрос, и он не уйдёт. Поэтому
        вызывающий оборачивает в `asyncio.shield` — см. `deep_research`.
        """
        rid, self._active_research_id = self._active_research_id, None
        if not rid or self._client is None:
            return False
        try:
            resp = await self._client.post(
                f"/api/terminate/{rid}", headers=self._headers(), timeout=10.0
            )
        except Exception:
            # Молча глотать нельзя: невыполненная отмена — это деньги, и о ней
            # надо узнавать из логов, а не по счёту от провайдера.
            logger.warning("LDR cancellation failed code=unavailable")
            return False
        if resp.status_code >= 400:
            logger.warning("LDR cancellation failed status_family=%sxx", resp.status_code // 100)
            return False
        logger.info("LDR cancellation completed")
        return True

    @property
    def active_research_id(self) -> str | None:
        """id незавершённого прогона, либо None. Читает слой отмены."""
        return self._active_research_id

    async def iter_status(self, research_id: str) -> AsyncGenerator[dict[str, Any]]:
        """Опрос статуса, ЙИЛДЯ каждый ответ, до завершения (дедлайн self._timeout).

        Нормальное завершение генератора = research готов. Поднимает
        `LDRResearchFailed` при ошибке на стороне LDR и `LDRTimeout` по дедлайну.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._timeout
        while True:
            data = await self._get(f"/api/research/{research_id}/status")
            state = str(_first(data, "status", "state") or "").strip().lower()
            yield data
            if state in _DONE_STATES:
                return
            if state in _FAILED_STATES:
                raise LDRResearchFailed()
            if loop.time() >= deadline:
                raise LDRTimeout()
            await asyncio.sleep(self._poll_interval)

    async def report(self, research_id: str) -> dict[str, Any]:
        data = await self._get(f"/api/report/{research_id}")
        # Отчёт получен — прогон завершён штатно, отменять нечего. Без сброса слой
        # отмены слал бы `POST /api/terminate` на КАЖДЫЙ успешный ресёрч: лишний
        # запрос и вводящая в заблуждение строка в логах про остановку.
        if self._active_research_id == research_id:
            self._active_research_id = None
        summary = _first(data, "summary", "report", "content", "markdown", "result")
        sources = _first(data, "sources", "citations", "links", "references") or []
        if not isinstance(sources, list):
            sources = []
        # Режем встроенный LDR-хвост Sources/Research Metrics — свой блок источников
        # добавит агент (иначе дубли). Инлайн-цитаты [n] в тексте остаются.
        clean = _strip_report_tail(str(summary or "").strip())
        return {"summary": clean, "sources": sources}

    async def metrics(self, research_id: str) -> dict[str, Any] | None:
        """Реальные токены research для точного биллинга. None → агент оценит сам.

        Схема LDR: {"status": "success", "metrics": {"total_tokens": N,
        "model_usage": [{"prompt_tokens", "completion_tokens", "tokens", "model"}]}}.
        Верхнего prompt/completion нет — суммируем по model_usage.
        """
        try:
            data = await self._get(f"/metrics/api/metrics/research/{research_id}")
        except LDRUnavailableError:
            return None
        node = data.get("metrics") if isinstance(data, dict) else None
        if not isinstance(node, dict):
            node = data if isinstance(data, dict) else {}
        prompt = completion = 0
        model = self._model
        usage = node.get("model_usage")
        if isinstance(usage, list):
            for mu in usage:
                if not isinstance(mu, dict):
                    continue
                prompt += int(mu.get("prompt_tokens") or mu.get("input_tokens") or 0)
                completion += int(mu.get("completion_tokens") or mu.get("output_tokens") or 0)
                model = mu.get("model") or model
        # Фолбэки на плоскую схему, если она вдруг иная.
        if not prompt:
            prompt = int(_first(node, "prompt_tokens", "input_tokens", "input") or 0)
        if not completion:
            completion = int(_first(node, "completion_tokens", "output_tokens", "output") or 0)
        total = int(_first(node, "total_tokens", "total") or 0) or (prompt + completion)
        if total <= 0:
            return None
        return {
            "prompt": prompt,
            "completion": completion,
            "total": total,
            "model": _strip_provider_prefix(model),
        }
