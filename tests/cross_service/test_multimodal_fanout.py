"""Tests for the multimodal fan-out agent pipeline.

Что осталось в backend'е: ``test_upload_classifies_code_and_data`` — он про
``UploadFileUseCase._extract_text``, то есть про то, как backend раскладывает залитый
файл по типам (code/csv/json/text). Веер получает уже готовые вложения и о разборе
файлов ничего не знает, так что здесь этот тест был бы про фейк.
"""

import pytest

from service.application.processor import AgentProcessor
from service.domain.pipeline import multimodal as mm
from service.domain.usage_ledger import UsageKind
from service.events import AgentEvent, EventType
from service.schemas.agents import ModalityAttachment


def test_normalize_attachments_filters_empty_and_malformed():
    raw = [
        {"kind": "image", "name": "a.png", "content": "кот на фото"},
        {"kind": "audio", "name": "v.webm", "content": "   "},  # пустой контент
        {"kind": "document", "name": "d.txt"},  # нет content
        "garbage",  # не dict
        ModalityAttachment(kind="document", name="b.pdf", content="текст"),
    ]
    result = mm.normalize_attachments(raw)
    assert [a.kind for a in result] == ["image", "document"]
    assert all(a.content.strip() for a in result)


def test_modality_analyst_registry_covers_file_kinds():
    from service.domain.subagents.modality_analysts import get_modality_analyst

    assert get_modality_analyst("image").kind == "image"
    assert get_modality_analyst("audio").kind == "audio"
    assert get_modality_analyst("data").kind == "data"
    assert get_modality_analyst("code").kind == "code"
    assert get_modality_analyst("document").kind == "document"
    # неизвестная модальность -> безопасный дефолт
    assert get_modality_analyst("whatever").kind == "document"


def test_should_fan_out_rules():
    two = [
        ModalityAttachment(kind="image", name="a", content="x"),
        ModalityAttachment(kind="audio", name="b", content="y"),
    ]
    one = two[:1]
    assert mm.should_fan_out(two) is True
    assert mm.should_fan_out(one) is False
    # маршруты-генераторы не фанятся, даже при нескольких вложениях
    assert mm.should_fan_out(two, route_override="image_gen") is False


class _StubAnalyst:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    async def analyze(self, *, user_input: str, name: str, content: str, execution=None) -> str:
        # Имитируем реальный провайдерский вызов: аналитик тратит токены.
        if execution is not None:
            execution.usage.record_usage(
                {"prompt": 100, "completion": 20},
                model="gpt-4o-mini",
                kind=UsageKind.MULTIMODAL,
            )
        return f"Анализ[{self.kind}]: {content[:24]}"


class _FakeGeneral:
    name = "general"

    def __init__(self) -> None:
        self.last_input: str | None = None
        self.last_context = None

    async def process(self, user_input, context):
        self.last_input = user_input
        self.last_context = context
        yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="OK")


@pytest.mark.asyncio
async def test_run_modality_fanout_aggregates(monkeypatch):
    monkeypatch.setattr(mm, "get_modality_analyst", lambda kind: _StubAnalyst(kind))

    attachments = [
        ModalityAttachment(kind="image", name="pic.png", content="на фото кот"),
        ModalityAttachment(kind="audio", name="voice.webm", content="привет это запись"),
    ]
    aggregated, events = await mm.run_modality_fanout(attachments=attachments, user_input="опиши")

    assert "Агрегированный мультимодальный контекст" in aggregated
    assert "Анализ[image]" in aggregated
    assert "Анализ[audio]" in aggregated
    # Разбор вложения — НЕ вызов инструмента. На tool-событии сериализатор кладёт `data`
    # ещё и в `tool_name`, и фронт печатал «Инструмент завершен: Проанализирована
    # модальность — Документ: x.md»: два ярлыка об одном и том же в одной строке.
    parsed = [
        e
        for e in events
        if e.type == EventType.STATUS_UPDATE and e.agent_name == "multimodal" and str(e.data or "")
    ]
    assert len(parsed) == 3, "статус старта + по строке на каждое вложение"
    assert not [e for e in events if e.type == EventType.TOOL_CALL_COMPLETE], (
        "fan-out снова притворяется инструментом"
    )

    # Аудит: каждый аналитик — отдельный LLM-вызов, веер должен тарифицироваться.
    # Один агрегированный token_usage на оба вложения (2×120 = 240 total).
    usage_events = [e for e in events if e.metadata and e.metadata.get("token_usage")]
    assert len(usage_events) == 1, "fan-out обязан эмитить ровно один token_usage"
    tu = usage_events[0].metadata["token_usage"]
    assert tu["prompt"] == 200 and tu["completion"] == 40 and tu["total"] == 240
    assert tu["model"] == "gpt-4o-mini", "без модели цена ушла бы в дефолт"


@pytest.mark.asyncio
async def test_processor_multimodal_routes_to_general_with_aggregated_context(monkeypatch):
    monkeypatch.setattr(mm, "get_modality_analyst", lambda kind: _StubAnalyst(kind))

    processor = AgentProcessor()
    fake_general = _FakeGeneral()
    processor.orchestrator._agents["general"] = fake_general

    attachments = [
        {"kind": "image", "name": "pic.png", "content": "на фото кот"},
        {"kind": "audio", "name": "voice.webm", "content": "привет это запись"},
    ]

    events = []
    async for event in processor.process_message_stream(
        "опиши вложения", "t1", user_id=None, attachments=attachments
    ):
        events.append(event)

    routing_complete = next(e for e in events if e.type == EventType.ROUTING_COMPLETE)
    assert routing_complete.agent_name == "general"
    assert routing_complete.metadata.get("multimodal") is True
    assert routing_complete.metadata.get("modalities_count") == 2

    parsed = [
        e
        for e in events
        if e.type == EventType.STATUS_UPDATE
        and e.agent_name == "multimodal"
        and str(e.data or "").startswith("Разобрано")
    ]
    assert len(parsed) == 2, "по строке на каждое вложение"

    # Агрегированный контекст уходит в system_context (а не в текст вопроса).
    system_context = fake_general.last_context.system_context or ""
    assert "Агрегированный мультимодальный контекст" in system_context
    assert "Анализ[image]" in system_context
    assert "Анализ[audio]" in system_context


async def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


@pytest.mark.asyncio
async def test_assess_complexity_heuristics(monkeypatch):
    from service.domain.routing import complexity as cx

    # Короткий запрос без маркеров — простой (LLM не вызывается).
    assert await cx.assess_is_complex("привет, как дела") is False

    # Есть маркеры сложности, но модель недоступна -> эвристический fallback = True.
    monkeypatch.setattr(
        "service.domain.client.list_available_models",
        await _async_return([]),
    )
    assert (
        await cx.assess_is_complex("сравни подходы и разработай план поэтапно, обоснуй выбор")
        is True
    )


@pytest.mark.asyncio
async def test_processor_plan_strategy_for_complex_general(monkeypatch):
    async def _always_complex(_user_input, **_kwargs):
        return True

    async def _fake_build_plan(_user_input, **_kwargs):
        return "1. Разобрать\n2. Решить\n3. Проверить", [
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name="planner",
                data="Задача сложная — строю план решения",
                metadata={"strategy": "plan"},
            )
        ]

    # ⚠️ ПАТЧИМ ТАМ, ГДЕ ЧИТАЮТ: гейт переехал в `pipeline/planning.py::resolve_plan`.
    monkeypatch.setattr("service.domain.pipeline.planning.assess_is_complex", _always_complex)
    monkeypatch.setattr("service.domain.pipeline.planning.build_plan", _fake_build_plan)

    processor = AgentProcessor()
    fake_general = _FakeGeneral()
    processor.orchestrator._agents["general"] = fake_general

    events = []
    # input_type=image форсит general без LLM-роутинга
    async for event in processor.process_message_stream(
        "спроектируй архитектуру сервиса", "t1", user_id=None, input_type="image"
    ):
        events.append(event)

    assert any(e.agent_name == "planner" for e in events)
    assert "План решения" in (fake_general.last_context.system_context or "")


@pytest.mark.asyncio
async def test_processor_no_plan_for_simple_general(monkeypatch):
    processor = AgentProcessor()
    fake_general = _FakeGeneral()
    processor.orchestrator._agents["general"] = fake_general

    events = []
    async for event in processor.process_message_stream(
        "опиши кратко", "t1", user_id=None, input_type="image"
    ):
        events.append(event)

    assert not any(e.agent_name == "planner" for e in events)
    assert "План решения" not in (fake_general.last_context.system_context or "")


@pytest.mark.asyncio
async def test_processor_single_attachment_keeps_legacy_path(monkeypatch):
    processor = AgentProcessor()
    fake_general = _FakeGeneral()
    processor.orchestrator._agents["general"] = fake_general

    # 1 вложение -> без fan-out; input_type=image форсит general без LLM-роутинга
    events = []
    async for event in processor.process_message_stream(
        "что на фото",
        "t1",
        user_id=None,
        input_type="image",
        file_context="на фото кот",
        attachments=[{"kind": "image", "name": "pic.png", "content": "на фото кот"}],
    ):
        events.append(event)

    routing_complete = next(e for e in events if e.type == EventType.ROUTING_COMPLETE)
    assert routing_complete.metadata.get("multimodal") is not True
    # никаких multimodal tool-call событий
    assert not [e for e in events if e.agent_name == "multimodal"]
    # general получил file_context (legacy single) через system_context
    assert "на фото кот" in (fake_general.last_context.system_context or "")


@pytest.mark.asyncio
async def test_attachment_suppresses_auto_knowledge(monkeypatch):
    """Вложение в ходе → база знаний НЕ подмешивается.

    Живой баг: юзер приложил «А - рассылка.json», а модель разобрала СТАРЫЙ
    «TG-forum-…pdf» из базы знаний и назвала его «загруженным файлом» (auto_knowledge
    форматирует хиты как `[имя]\nтекст` — это и всплыло в ответе). Когда файл приложен,
    вопрос про НЕГО, и recall по архиву только путает модель.
    """
    called = {"n": 0}

    async def _fake_knowledge(self, user_id, user_input):
        called["n"] += 1
        return "[старый.pdf]\nстарый текст из базы знаний"

    monkeypatch.setattr(AgentProcessor, "_auto_knowledge", _fake_knowledge)

    processor = AgentProcessor()
    fake_general = _FakeGeneral()
    processor.orchestrator._agents["general"] = fake_general

    async for _ in processor.process_message_stream(
        "разбери файл",
        "t1",
        user_id="u1",
        input_type="image",
        file_context="СОДЕРЖИМОЕ ФАЙЛА",
    ):
        pass

    assert called["n"] == 0, "база знаний подмешана поверх вложения — модель спутает файлы"
    sys_ctx = fake_general.last_context.system_context or ""
    assert "СОДЕРЖИМОЕ ФАЙЛА" in sys_ctx
    assert "старый.pdf" not in sys_ctx


@pytest.mark.asyncio
async def test_no_attachment_still_uses_auto_knowledge(monkeypatch):
    """Без вложения база знаний работает как раньше (для моделей без tools)."""
    called = {"n": 0}

    async def _fake_knowledge(self, user_id, user_input):
        called["n"] += 1
        return "[дока.pdf]\nнужный фрагмент"

    monkeypatch.setattr(AgentProcessor, "_auto_knowledge", _fake_knowledge)

    processor = AgentProcessor()
    fake_general = _FakeGeneral()
    processor.orchestrator._agents["general"] = fake_general

    async for _ in processor.process_message_stream(
        "что там про сроки",
        "t1",
        user_id="u1",
        input_type="image",
    ):
        pass

    assert called["n"] == 1
    assert "нужный фрагмент" in (fake_general.last_context.system_context or "")
