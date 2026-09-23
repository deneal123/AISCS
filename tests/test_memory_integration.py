import pytest

from service.infrastructure.memory.base import (
    BaseIntegration,
    BaseMemoryIntegration,
)
from service.infrastructure.memory.mem0 import Mem0MemoryIntegration
from service.infrastructure.messaging.tasks import _resolve_memory_user_id
from service.services.analytics.application.memory_service import MemoryService


class _FakeMem0Client:
    def __init__(self) -> None:
        self.saved_calls: list[dict] = []

    def search(self, query: str, user_id: str, top_k: int = 5):  # noqa: ANN001
        return {
            "results": [
                {"memory": "Пользователь предпочитает короткие ответы"},
                {"memory": "Работает с FastAPI"},
            ]
        }

    def add(self, messages, user_id: str, metadata=None):  # noqa: ANN001
        self.saved_calls.append(
            {
                "messages": messages,
                "user_id": user_id,
                "metadata": metadata,
            }
        )
        return {"status": "ok"}


class _FakeIntegration(BaseMemoryIntegration):
    def __init__(self) -> None:
        super().__init__(name="fake")
        self.saved: list[dict] = []

    @property
    def available(self) -> bool:
        return True

    async def get_memory_context(self, *, user_id: str, top_k: int = 5) -> str:
        return f"memory-for-{user_id}-k{top_k}"

    async def save_messages(
        self, *, user_id: str, messages: list[dict], metadata: dict | None = None
    ) -> None:
        self.saved.append({"user_id": user_id, "messages": messages, "metadata": metadata})

    async def list_facts(
        self, *, user_id: str, query: str | None = None, top_k: int = 50
    ) -> list[dict]:
        return []

    async def add_fact(
        self, *, user_id: str, fact_type: str, fact_key: str, fact_value: str
    ) -> dict:
        return {}

    async def delete_fact(self, *, user_id: str, fact_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_mem0_integration_formats_context_from_results() -> None:
    integration = Mem0MemoryIntegration(client=_FakeMem0Client())

    context = await integration.get_memory_context(user_id="user-1", top_k=3)

    assert "Контекст из памяти пользователя" in context
    assert "Пользователь предпочитает короткие ответы" in context
    assert "Работает с FastAPI" in context


@pytest.mark.asyncio
async def test_mem0_integration_saves_messages() -> None:
    client = _FakeMem0Client()
    integration = Mem0MemoryIntegration(client=client)

    await integration.save_messages(
        user_id="user-2",
        messages=[{"role": "user", "content": "Мне нравятся диаграммы"}],
        metadata={"thread_id": "thread-1"},
    )

    assert len(client.saved_calls) == 1
    assert client.saved_calls[0]["user_id"] == "user-2"
    assert client.saved_calls[0]["messages"][0]["content"] == "Мне нравятся диаграммы"


class _FakeFactsRepo:
    """Фейковый реестр фактов (profile.user_memory_facts) для тестов."""

    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self._facts: list[dict] = []

    async def list_facts(self, *, user_id: str, limit: int = 50) -> list[dict]:
        return list(self._facts)

    async def upsert_fact(self, **kwargs) -> None:  # noqa: ANN003
        self.upserts.append(kwargs)
        self._facts.insert(
            0,
            {
                "id": kwargs["fact_id"],
                "fact_type": kwargs["fact_type"],
                "fact_key": kwargs["fact_key"],
                "fact_value": kwargs["fact_value"],
                "confidence": kwargs.get("confidence"),
                "updated_at": None,
            },
        )

    async def delete_fact(self, *, user_id: str, fact_id: str) -> bool:
        return True

    async def count_facts(self, *, user_id: str) -> int:
        return len(self._facts)


@pytest.mark.asyncio
async def test_memory_service_saves_structured_facts_to_own_registry() -> None:
    repo = _FakeFactsRepo()
    service = MemoryService(integration=_FakeIntegration(), facts_repo=repo)

    # Подменяем LLM-экстракцию детерминированным структурированным фактом.
    # usage_out — куда экстракция складывает токены вызова (по ним воркер тарифицирует
    # долговременную память); фейку он не нужен, но принять его обязан.
    async def _fake_extract(_messages, usage_out=None):
        return [{"type": "preference", "key": "диаграммы", "value": "Пользователь любит диаграммы"}]

    service._extract_structured_facts = _fake_extract

    await service.extract_and_save_facts(
        user_id="user-3",
        thread_id="thread-2",
        messages=[{"role": "user", "content": "Мне нравятся диаграммы"}],
    )

    assert len(repo.upserts) == 1
    up = repo.upserts[0]
    assert up["user_id"] == "user:user-3"
    assert up["fact_type"] == "preference"
    assert up["fact_key"] == "диаграммы"
    assert up["fact_value"] == "Пользователь любит диаграммы"
    assert up["source_thread_id"] == "thread-2"
    assert up["confidence"] is None  # без фейкового «99%»
    assert up["content_hash"]  # дедуп-ключ проставлен

    # get_memory_context теперь читает из собственного реестра, а не из MemOS.
    context = await service.get_memory_context("user-3", top_k=7)
    assert "Контекст из памяти пользователя" in context
    assert "Пользователь любит диаграммы" in context


@pytest.mark.asyncio
async def test_memory_service_skips_save_when_no_durable_facts() -> None:
    repo = _FakeFactsRepo()
    service = MemoryService(integration=_FakeIntegration(), facts_repo=repo)

    # Разовая просьба без устойчивых фактов → экстракция пуста → ничего не пишем.
    async def _empty_extract(_messages, usage_out=None):
        return []

    service._extract_structured_facts = _empty_extract

    await service.extract_and_save_facts(
        user_id="user-4",
        thread_id="thread-3",
        messages=[{"role": "user", "content": "Проверь адрес моей машины"}],
    )

    assert repo.upserts == []


def test_memory_integration_inherits_from_generic_base() -> None:
    integration = Mem0MemoryIntegration(client=_FakeMem0Client())

    assert isinstance(integration, BaseIntegration)
    assert isinstance(integration, BaseMemoryIntegration)


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDbSession:
    def __init__(self, value):
        self._value = value

    async def execute(self, *_args, **_kwargs):
        return _FakeScalarResult(self._value)


@pytest.mark.asyncio
async def test_resolve_memory_user_id_prefers_explicit_user() -> None:
    db = _FakeDbSession("from-thread")

    resolved = await _resolve_memory_user_id(
        db_session=db, user_id="real-user", thread_id="thread-1"
    )

    assert resolved == "real-user"


@pytest.mark.asyncio
async def test_resolve_memory_user_id_falls_back_to_thread_owner() -> None:
    db = _FakeDbSession("thread-owner-user")

    resolved = await _resolve_memory_user_id(
        db_session=db,
        user_id="00000000-0000-0000-0000-000000000000",
        thread_id="thread-2",
    )

    assert resolved == "thread-owner-user"
