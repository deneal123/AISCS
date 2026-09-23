"""MemOS-backed memory integration for agent layer.

Адаптер к MemOS (MemTensor) поверх существующего порта BaseMemoryIntegration —
провайдер-агностичный: одинаково работает с self-hosted MemOS-сервисом и с
MemOS Cloud (различаются base_url и наличие api_key). Общение по REST через httpx
(`/product/add`, `/product/search`). Полностью fail-open: любая ошибка провайдера
логируется и проглатывается, чат никогда не ломается.

Изоляция по пользователям: каждому user_id соответствует свой mem_cube
(шаблон ``memos_mem_cube_id``, по умолчанию ``gpthub-{user_id}``).
"""

from __future__ import annotations

from typing import Any

import httpx

from service.infrastructure.memory.base import BaseMemoryIntegration
from service.settings import config

# Запрос для подтягивания релевантного профиля пользователя в контекст.
_CONTEXT_QUERY = "user preferences profile facts goals constraints recent context"
_CONTEXT_HEADER = "## Контекст из памяти пользователя:"
_MAX_CONTEXT_ITEMS = 10

# Сброс памяти идёт по Neo4j и Qdrant разом — это заметно дольше обычного запроса,
# поэтому у операции свой срок, а не общий `memos_timeout_sec`.
_WIPE_TIMEOUT_SEC = 45.0


class MemOSMemoryIntegration(BaseMemoryIntegration):
    """Memory provider backed by a MemOS REST endpoint (self-hosted or cloud)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        mem_cube_template: str | None = None,
        timeout: float | None = None,
        async_mode: str | None = None,
        default_top_k: int = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(name="memos")
        raw_base = base_url if base_url is not None else config.agents.memos_base_url
        self._base_url = (raw_base or "").rstrip("/")
        self._api_key = (api_key if api_key is not None else config.agents.memos_api_key).strip()
        self._mem_cube_template = (
            mem_cube_template if mem_cube_template is not None else config.agents.memos_mem_cube_id
        ) or "gpthub-{user_id}"
        raw_timeout = timeout if timeout is not None else config.agents.memos_timeout_sec
        self._timeout = raw_timeout or 15.0
        self._async_mode = (
            async_mode if async_mode is not None else config.agents.memos_async_mode
        ) or "sync"
        self._default_top_k = default_top_k
        self._transport = transport  # для тестов (httpx.MockTransport)

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def _cube_for(self, user_id: str) -> str:
        return self._mem_cube_template.replace("{user_id}", str(user_id))

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        """POST с проглатыванием ошибок (fail-open). Возвращает JSON или None."""
        started = self._log_operation_start(f"memos.post {path}")
        try:
            async with self._client() as client:
                resp = await client.post(path, json=body)
            if resp.status_code >= 400:
                self.logger.warning("MemOS %s -> HTTP %s", path, resp.status_code)
                return None
            data = resp.json()
            self._log_operation_success(f"memos.post {path}", started)
            return data if isinstance(data, dict) else {"data": data}
        except Exception as exc:  # defensive provider boundary
            self._log_operation_failure(f"memos.post {path}", started, exc)
            return None

    async def wipe(self) -> dict[str, Any]:
        """Полный сброс памяти MemOS: Neo4j `:Memory` + коллекция Qdrant.

        ⚠️ Метод собран здесь, потому что тот же вызов ЖИЛ В ДВУХ КОПИЯХ — в
        `admin_service` и в `admin_api`, обе на голом httpx мимо этого клиента. Копии
        не отправляли `Authorization`: при заполненном `AGENTS__MEMOS_API_KEY` сброс
        памяти получал бы 401, тогда как остальная интеграция работала бы. Дефект
        латентный ровно до того дня, когда ключ зададут.

        ⚠️ Ответ ЯВНЫЙ, а не fail-open `None`, как у `_post`. «Стёрли» и «не смогли
        стереть» здесь путать нельзя: администратор нажал «очистить», и рапорт об
        успехе при оставшихся в Qdrant текстах пользователя — прямой обман.
        """
        if not self.available:
            return {"ok": False, "reason": "no_memos_base_url"}
        started = self._log_operation_start("memos.wipe")
        try:
            async with self._client() as client:
                # Свой срок: сброс идёт по ДВУМ хранилищам разом и заметно дольше
                # обычного запроса памяти (`memos_timeout_sec`, по умолчанию 15 с).
                resp = await client.post("/product/admin/wipe", timeout=_WIPE_TIMEOUT_SEC)
        except Exception as exc:  # defensive provider boundary
            self._log_operation_failure("memos.wipe", started, exc)
            return {"ok": False, "error": type(exc).__name__}
        if resp.status_code >= 400:
            self.logger.warning("MemOS wipe -> HTTP %s", resp.status_code)
            return {"ok": False, "status": resp.status_code}
        self._log_operation_success("memos.wipe", started)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001 — тело не обязано быть JSON
            data = None
        return {"ok": True, "status": resp.status_code, "data": data}

    async def forget_user(self, *, user_id: str) -> dict[str, Any]:
        """Стереть память ОДНОГО пользователя (его куб в Neo4j + его векторы в Qdrant).

        ⚠️ Ответ ЯВНЫЙ, не fail-open `None`, как у `_post`, — по той же причине, что и у
        `wipe`: человек нажал «очистить память», и рапорт об успехе при оставшихся
        записях — прямой обман. Счётчики приходят от MemOS замером до удаления, поэтому
        по ним видно и «стёрли N», и «стирать было нечего».
        """
        if not user_id:
            return {"ok": False, "reason": "no_user_id"}
        if not self.available:
            return {"ok": False, "reason": "no_memos_base_url"}
        started = self._log_operation_start("memos.forget_user")
        try:
            async with self._client() as client:
                # Свой срок, как у `wipe`: удаление идёт по ДВУМ хранилищам разом.
                resp = await client.post(
                    "/product/admin/wipe_user",
                    json={"user_name": self._cube_for(user_id)},
                    timeout=_WIPE_TIMEOUT_SEC,
                )
        except Exception as exc:  # defensive provider boundary
            self._log_operation_failure("memos.forget_user", started, exc)
            return {"ok": False, "error": type(exc).__name__}
        if resp.status_code >= 400:
            self.logger.warning("MemOS forget_user -> HTTP %s", resp.status_code)
            return {"ok": False, "status": resp.status_code}
        self._log_operation_success("memos.forget_user", started)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001 — тело не обязано быть JSON
            data = {}
        stats = data.get("data") if isinstance(data, dict) else None
        return {"ok": True, **(stats if isinstance(stats, dict) else {})}

    @staticmethod
    def _iter_items(payload: dict[str, Any] | None) -> list[Any]:
        """Достать список элементов из разных форм ответа MemOS.

        `/product/add` возвращает `data` как плоский список воспоминаний.
        `/product/search` возвращает `data` как словарь групп по типу памяти
        (`text_mem`, `act_mem`, `para_mem`, `pref_mem`, ...), каждая из которых —
        список кубов вида `{"cube_id": ..., "memories": [...]}`. Нужно
        сплющить все `memories` из всех групп/кубов в один список.
        """
        if not isinstance(payload, dict):
            return []
        for key in ("data", "results", "memories", "items", "memory"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for inner_key in ("memories", "results", "items"):
                    inner = value.get(inner_key)
                    if isinstance(inner, list):
                        return inner
                items: list[Any] = []
                for group_key in ("text_mem", "act_mem", "para_mem", "pref_mem"):
                    group = value.get(group_key)
                    if not isinstance(group, list):
                        continue
                    for cube in group:
                        if not isinstance(cube, dict):
                            continue
                        cube_memories = cube.get("memories")
                        if isinstance(cube_memories, list):
                            items.extend(cube_memories)
                if items:
                    return items
        return []

    @staticmethod
    def _item_text(item: Any) -> str:
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in ("memory", "text", "content", "value", "summary"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        return ""

    async def get_memory_context(self, *, user_id: str, top_k: int = 5) -> str:
        if not user_id or not self.available:
            return ""
        payload = await self._post(
            "/product/search",
            {
                "query": _CONTEXT_QUERY,
                "user_id": str(user_id),
                "mem_cube_id": self._cube_for(user_id),
                "top_k": top_k or self._default_top_k,
                # Общий профильный запрос намеренно абстрактный ("user preferences
                # profile..."), поэтому его cosine-релевантность к конкретным фактам
                # часто ниже дефолтного порога MemOS (relativity >= 0.45) — тогда
                # он отбрасывает уже сохранённые факты. Здесь нужен весь профиль,
                # а не строгая релевантность, поэтому порог отключаем.
                "relativity": 0,
            },
        )
        texts: list[str] = []
        for item in self._iter_items(payload):
            text = self._item_text(item)
            if text:
                texts.append(text)
            if len(texts) >= _MAX_CONTEXT_ITEMS:
                break
        if not texts:
            return ""
        return _CONTEXT_HEADER + "\n" + "\n".join(f"- {t}" for t in texts)

    async def save_messages(
        self,
        *,
        user_id: str,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not user_id or not self.available or not messages:
            return
        norm = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "").strip()}
            for m in messages
            if str(m.get("content") or "").strip()
        ]
        if not norm:
            return
        body: dict[str, Any] = {
            "user_id": str(user_id),
            "mem_cube_id": self._cube_for(user_id),
            "messages": norm,
            "async_mode": self._async_mode,
        }
        if metadata:
            body["metadata"] = metadata
        await self._post("/product/add", body)

    async def list_facts(
        self,
        *,
        user_id: str,
        query: str | None = None,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        if not user_id or not self.available:
            return []
        payload = await self._post(
            "/product/search",
            {
                "query": query or _CONTEXT_QUERY,
                "user_id": str(user_id),
                "mem_cube_id": self._cube_for(user_id),
                "top_k": top_k,
                "relativity": 0 if not query else 0.45,
            },
        )
        facts: list[dict[str, Any]] = []
        for item in self._iter_items(payload):
            if isinstance(item, dict):
                facts.append(item)
            elif isinstance(item, str) and item.strip():
                facts.append({"fact_value": item.strip()})
        return facts

    async def add_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        fact_value: str,
    ) -> dict[str, Any]:
        if not user_id or not self.available:
            return {}
        content = f"{fact_key}: {fact_value}".strip().strip(":").strip()
        await self.save_messages(
            user_id=user_id,
            messages=[{"role": "user", "content": content}],
            metadata={"fact_type": fact_type, "fact_key": fact_key, "source": "manual"},
        )
        return {"fact_type": fact_type, "fact_key": fact_key, "fact_value": fact_value}

    async def delete_fact(self, *, user_id: str, fact_id: str) -> bool:
        """Удаление по ID. Эндпоинт MemOS не стандартизован — best-effort."""
        if not user_id or not self.available or not fact_id:
            return False
        payload = await self._post(
            "/product/delete",
            {
                "user_id": str(user_id),
                "mem_cube_id": self._cube_for(user_id),
                "memory_id": str(fact_id),
            },
        )
        return payload is not None

    async def dashboard(self, *, user_id: str) -> dict[str, Any]:
        """Дашборд памяти MemOS для куба пользователя: факты по типам (text/pref/
        tool/skill) + счётчики (/product/get_memory_dashboard). Fail-open → {}."""
        if not user_id or not self.available:
            return {}
        payload = await self._post(
            "/product/get_memory_dashboard",
            {"mem_cube_id": self._cube_for(user_id), "user_id": str(user_id)},
        )
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        return data if isinstance(data, dict) else {}


async def wipe_memos_memory() -> dict[str, Any]:
    """Сброс всей памяти MemOS одной функцией — точка входа для админки.

    ⚠️ Заведена, потому что этот вызов лежал В ДВУХ КОПИЯХ (`admin_service` и
    `admin_api`), обе на голом httpx мимо клиента MemOS и обе БЕЗ заголовка
    авторизации. Пока `AGENTS__MEMOS_API_KEY` пуст, разницы не видно; в день, когда его
    зададут, сброс памяти начал бы получать 401, а остальная интеграция продолжила бы
    работать — то есть кнопка «очистить» молча перестала бы очищать.
    """
    return await MemOSMemoryIntegration().wipe()
