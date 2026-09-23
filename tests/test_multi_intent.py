"""Тесты Фазы 2: декомпозиция мульти-интента, ре-роут, исполнение шагов."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.domain.pipeline import decomposition
from service.domain.pipeline.decomposition import (
    SubTask,
    decompose_intents,
    looks_multi_intent,
)
from service.domain.pipeline.execution_plan import execute_steps, run_with_reroute
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext


def _ctx():
    return UserContext(user_id="1", request_time=datetime.now(UTC), system_context="BASE")


def _chunk(text):
    return AgentEvent(type=EventType.STREAM_CHUNK, data=text)


def _err(text="boom"):
    return AgentEvent(type=EventType.ERROR, data=text)


class _Agent:
    def __init__(self, events):
        self._events = events
        self.calls = 0

    async def process(self, user_input, context):
        self.calls += 1
        for e in self._events:
            yield e


class _Orch:
    def __init__(self, agents):
        self._agents = agents

    def get_agent(self, name):
        return self._agents.get(name) or self._agents["general"]


# --------------------------------------------------------------------------- #
# decomposition pure helpers                                                    #
# --------------------------------------------------------------------------- #
def test_looks_multi_intent():
    assert looks_multi_intent("найди X, затем сделай презентацию")
    assert looks_multi_intent("do X then do Y")
    assert not looks_multi_intent("просто ответь на вопрос")


def test_parse_subtasks_filters_invalid():
    raw = (
        '[{"category":"web_search","instruction":"a"},'
        '{"category":"bogus","instruction":"b"},'
        '{"category":"pptx_gen","instruction":"c"}]'
    )
    out = decomposition._parse_subtasks(raw)
    assert [s.category for s in out] == ["web_search", "pdf_gen"]


def test_parse_subtasks_reads_independent_flag():
    # P3.2: декомпозиция помечает независимые (параллелимые) подзадачи.
    raw = (
        '[{"category":"web_search","instruction":"a","independent":true},'
        '{"category":"image_gen","instruction":"b"}]'
    )
    out = decomposition._parse_subtasks(raw)
    assert out[0].independent is True
    assert out[1].independent is False  # по умолчанию зависимая (безопасно-последовательно)


def test_decompose_prompt_matches_allowed_categories():
    # P1.5: раньше промпт предлагал audio_transcribe, а _parse_subtasks его молча
    # отсекал (нет в ALLOWED_CATEGORIES) — промпт и фильтр расходились, шаг терялся.
    assert "audio_transcribe" not in decomposition._decompose_prompt().lower()


def test_parse_subtasks_strips_code_fence():
    raw = '```json\n[{"category":"general","instruction":"x"}]\n```'
    out = decomposition._parse_subtasks(raw)
    assert len(out) == 1 and out[0].category == "general"


@pytest.mark.asyncio
async def test_decompose_returns_none_for_single_intent():
    # нет союзных маркеров → пре-фильтр отсекает без LLM
    assert await decompose_intents("просто объясни рекурсию") is None


@pytest.mark.asyncio
async def test_decompose_returns_subtasks(monkeypatch):
    import service.domain.client as client_mod
    from service.domain.subagents import utils as utils_mod

    async def _models(*a, **k):
        return ["gpt-x"]

    async def _create(**kwargs):
        content = (
            '[{"category":"web_search","instruction":"найди X"},'
            '{"category":"pptx_gen","instruction":"сделай презентацию"}]'
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _create)
    monkeypatch.setattr(utils_mod, "pick_text_model", lambda models: "gpt-x")

    out = await decompose_intents("найди X, затем сделай презентацию", max_subtasks=3)
    assert [s.category for s in out] == ["web_search", "pdf_gen"]


# --------------------------------------------------------------------------- #
# run_with_reroute                                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reroute_on_early_error():
    failing = _Agent([_err("web down")])
    general = _Agent([_chunk("ответ general")])
    orch = _Orch({"web_search": failing, "general": general})

    events = [
        e
        async for e in run_with_reroute(
            orchestrator=orch, agent_name="web_search", user_input="q", context=_ctx()
        )
    ]
    chunks = [e.data for e in events if e.type == EventType.STREAM_CHUNK]
    assert "".join(chunks) == "ответ general"
    assert all(e.type != EventType.ERROR for e in events)  # ошибка проглочена
    assert general.calls == 1


@pytest.mark.asyncio
async def test_no_reroute_on_success():
    good = _Agent([_chunk("hi"), _chunk(" there")])
    general = _Agent([_chunk("SHOULD NOT RUN")])
    orch = _Orch({"web_search": good, "general": general})

    events = [
        e
        async for e in run_with_reroute(
            orchestrator=orch, agent_name="web_search", user_input="q", context=_ctx()
        )
    ]
    assert "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK) == "hi there"
    assert general.calls == 0


@pytest.mark.asyncio
async def test_no_reroute_after_content():
    # контент пошёл, затем ошибка — ре-роут запрещён (пользователь уже видит ответ)
    mixed = _Agent([_chunk("partial"), _err("late fail")])
    general = _Agent([_chunk("NOPE")])
    orch = _Orch({"web_search": mixed, "general": general})

    events = [
        e
        async for e in run_with_reroute(
            orchestrator=orch, agent_name="web_search", user_input="q", context=_ctx()
        )
    ]
    assert any(e.type == EventType.ERROR for e in events)
    assert general.calls == 0


@pytest.mark.asyncio
async def test_no_reroute_on_guardrail_block():
    # P0.4: блокировка небезопасного входа НЕ должна ре-роутиться на general
    # (у которого свой вход-гейт) — иначе блок становится no-op.
    blocked = _Agent(
        [
            AgentEvent(
                type=EventType.ERROR,
                agent_name="web_search",
                data="Запрос затрагивает небезопасную тему.",
                metadata={"guardrail_block": True},
            )
        ]
    )
    general = _Agent([_chunk("НЕ ДОЛЖЕН ЗАПУСТИТЬСЯ")])
    orch = _Orch({"web_search": blocked, "general": general})

    events = [
        e
        async for e in run_with_reroute(
            orchestrator=orch, agent_name="web_search", user_input="q", context=_ctx()
        )
    ]
    assert any(e.type == EventType.ERROR for e in events)  # блок прокинут как есть
    assert general.calls == 0  # ре-роута не было


@pytest.mark.asyncio
async def test_reroute_disabled_passes_error():
    failing = _Agent([_err("x")])
    general = _Agent([_chunk("NOPE")])
    orch = _Orch({"web_search": failing, "general": general})

    events = [
        e
        async for e in run_with_reroute(
            orchestrator=orch,
            agent_name="web_search",
            user_input="q",
            context=_ctx(),
            reroute_enabled=False,
        )
    ]
    assert any(e.type == EventType.ERROR for e in events)
    assert general.calls == 0


@pytest.mark.asyncio
async def test_artifact_agent_can_forbid_prose_fallback_after_build_failure():
    failing = _Agent([_err("document build unavailable")])
    failing.allow_failure_reroute = False
    general = _Agent([_chunk("PDF готов: test.pdf")])
    orch = _Orch({"pdf_gen": failing, "general": general})

    events = [
        event
        async for event in run_with_reroute(
            orchestrator=orch,
            agent_name="pdf_gen",
            user_input="создай PDF",
            context=_ctx(),
        )
    ]

    assert any(event.type == EventType.ERROR for event in events)
    assert not any(event.type == EventType.STREAM_CHUNK for event in events)
    assert general.calls == 0


# --------------------------------------------------------------------------- #
# execute_steps                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_execute_steps_streams_only_final_synthesis():
    ws = _Agent([_chunk("WS-result")])
    pptx = _Agent([_chunk("PPTX-result")])
    general = _Agent([_chunk("ИТОГ")])
    orch = _Orch({"web_search": ws, "pptx_gen": pptx, "general": general})
    subtasks = [SubTask("web_search", "найди"), SubTask("pptx_gen", "сделай слайды")]

    events = [
        e
        async for e in execute_steps(
            orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="q"
        )
    ]
    # только синтез (general) стримит контент пользователю
    chunks = [e.data for e in events if e.type == EventType.STREAM_CHUNK]
    assert "".join(chunks) == "ИТОГ"
    # промежуточные шаги исполнились
    assert ws.calls == 1 and pptx.calls == 1 and general.calls == 1

    # Ход шагов виден через ЕДИНЫЙ прогресс-бар, а не россыпь трейс-строк: шаги шлют
    # STATUS_UPDATE с kind=multi_intent_progress (фронт роутит их в updateTraceProgress).
    # Раньше здесь ожидались TOOL_CALL_COMPLETE — их убрали вместе с «россыпью».
    progress = [
        e
        for e in events
        if e.type == EventType.STATUS_UPDATE
        and (e.metadata or {}).get("kind") == "multi_intent_progress"
    ]
    assert progress, "ход мульти-интента не виден в трейсе"
    # Бар доходит до конца и не идёт вспять.
    values = [e.metadata["progress"] for e in progress]
    assert values[0] == 0 and values[-1] == 100
    assert values == sorted(values)


# --------------------------------------------------------------------------- #
# P3.2: независимые подзадачи исполняются ПАРАЛЛЕЛЬНО                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_execute_steps_runs_independent_steps_in_parallel():
    """independent-шаги должны идти РАЗОМ. Проверяем через Barrier(2): оба агента
    доходят до барьера только если исполняются одновременно; при последовательном
    пути первый заблокировался бы и wait_for упал бы по таймауту."""
    import asyncio

    barrier = asyncio.Barrier(2)

    class _ConcurrentAgent:
        def __init__(self, tag):
            self.tag = tag
            self.calls = 0

        async def process(self, user_input, context):
            self.calls += 1
            await asyncio.wait_for(barrier.wait(), timeout=2.0)  # зависнет, если не параллельно
            yield AgentEvent(type=EventType.STREAM_CHUNK, data=f"{self.tag}-result")
            yield _complete_with_usage(10, 5, f"m-{self.tag}")

    captured: dict = {}

    class _CapGeneral:
        calls = 0

        async def process(self, user_input, context):
            _CapGeneral.calls += 1
            captured["prompt"] = user_input
            yield _chunk("ИТОГ")

    a = _ConcurrentAgent("A")
    b = _ConcurrentAgent("B")
    orch = _Orch({"web_search": a, "image_gen": b, "general": _CapGeneral()})
    subtasks = [
        SubTask(category="web_search", instruction="x", independent=True),
        SubTask(category="image_gen", instruction="y", independent=True),
    ]

    events = [
        e
        async for e in execute_steps(
            orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="q"
        )
    ]

    # Оба шага реально исполнились параллельно (барьер прошёл, таймаута нет).
    assert a.calls == 1 and b.calls == 1
    # Пользователю стримит ТОЛЬКО синтез.
    assert "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK) == "ИТОГ"
    # Бар доходит до 100 и не идёт вспять.
    progress = [
        e.metadata["progress"]
        for e in events
        if e.type == EventType.STATUS_UPDATE
        and (e.metadata or {}).get("kind") == "multi_intent_progress"
    ]
    assert progress[0] == 0 and progress[-1] == 100 and progress == sorted(progress)
    # accumulated восстановлен в ИСХОДНОМ порядке (A перед B) несмотря на порядок завершения.
    assert captured["prompt"].index("A-result") < captured["prompt"].index("B-result")


@pytest.mark.asyncio
async def test_execute_steps_parallel_forwards_usage_and_artifacts():
    """Параллельный путь тоже обязан пробрасывать usage (биллинг) и артефакты."""
    from service.application.reply_assembler import ReplyAssembler

    img = _Agent(
        [
            AgentEvent(
                type=EventType.STREAM_CHUNK,
                data="картинка готова",
                metadata={"b64_json": "AAAA"},
            ),
            _complete_with_usage(100, 50, "m-img"),
        ]
    )
    ws = _Agent([_chunk("нашёл"), _complete_with_usage(30, 20, "m-ws")])
    synth = _Agent([_chunk("ИТОГ")])
    orch = _Orch({"image_gen": img, "web_search": ws, "general": synth})
    subtasks = [
        SubTask(category="image_gen", instruction="нарисуй", independent=True),
        SubTask(category="web_search", instruction="найди", independent=True),
    ]

    asm = ReplyAssembler()
    async for e in execute_steps(
        orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="q"
    ):
        asm.consume(
            event=e,
            stream_chunk_type=EventType.STREAM_CHUNK,
            error_type=EventType.ERROR,
            structured_output_type=EventType.STRUCTURED_OUTPUT,
        )

    assert "".join(asm.reply_parts) == "ИТОГ"
    pending = asm.metadata.get("_pending_artifacts") or []
    assert any(a.get("b64_json") == "AAAA" for a in pending), (
        "артефакт потерян на параллельном пути"
    )
    models = sorted(c["model"] for c in asm.per_call_usage)
    assert models == ["m-img", "m-ws"], f"usage недосчитан на параллельном пути: {models}"


# --------------------------------------------------------------------------- #
# Мульти-интент и вложения ортогональны                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_attachments_do_not_cancel_multi_intent(monkeypatch) -> None:
    """Декомпозиция обязана работать И с вложениями.

    Была регрессия: мульти-интент жил в `else` к `if multimodal`, поэтому ЛЮБЫЕ два
    вложения молча отменяли его — человек жал тумблер, прикладывал файлы и получал
    обычный однопроходный ответ, не понимая, почему кнопка «не работает». Fan-out
    готовит КОНТЕКСТ, декомпозиция делит ЗАДАЧУ; одно не отменяет другое.

    ⚠️ Проверяем ПОВЕДЕНИЕ, а не текст исходника. Прежняя версия искала в
    `inspect.getsource` порядок `run_modality_fanout` и `decompose_intents` — и
    сломалась при обычном переносе кода в отдельный метод, хотя ничего не изменилось.
    Такой страж красит сборку на рефакторингах и молчит на настоящих регрессиях: стоит
    заново завернуть декомпозицию в `else` с другим отступом, и подстрока найдётся.
    """
    from service.application import processor_steps as steps_mod
    from service.application.processor import AgentProcessor
    from service.domain.pipeline import multimodal as mm

    seen: dict = {}

    async def _spy_decompose(user_input, **kw):
        seen["called"] = True
        return []

    async def _fanout(*, attachments, user_input, execution=None):
        assert execution is not None
        seen["fanout"] = len(attachments)
        return "разобранные вложения", []

    monkeypatch.setattr(steps_mod, "decompose_intents", _spy_decompose)
    # ⚠️ ПАТЧИМ ТАМ, ГДЕ ЧИТАЮТ: fan-out переехал в свой модуль вместе с темой, и
    # подмена в шаге теперь не действует — шаг зовёт `fanout_context`, а тот его соседа.
    from service.domain.pipeline import multimodal as multimodal_mod

    monkeypatch.setattr(multimodal_mod, "run_modality_fanout", _fanout)
    # ⚠️ ПАТЧИМ ТАМ, ГДЕ ЧИТАЮТ: гейт декомпозиции переехал в свой модуль, и подмена
    # `_agent_flag` в шагах конвейера перестала на него влиять. Здесь это выразилось
    # падением, но точно так же оно могло остаться зелёным и не проверять ничего —
    # `steps_mod._agent_flag` в файле по-прежнему есть.
    monkeypatch.setattr(steps_mod, "_agent_flag", lambda name, default: True)
    monkeypatch.setattr(mm, "get_modality_analyst", lambda kind: None)

    proc = AgentProcessor()
    proc.orchestrator._agents["general"] = _Agent([_chunk("ОТВЕТ")])

    async for _ in proc.process_message_stream(
        "найди X, затем сделай презентацию",
        "t-both",
        user_id=None,
        session=None,
        input_type="text",
        # ⚠️ Просим декомпозицию ЯВНО, а не через глобальный флаг. Гейт переехал в свой
        # модуль, и подмена `_agent_flag` в шагах конвейера на него больше не влияет
        # («патчь там, где читают»). Патчить же метод общего синглтона настроек нельзя:
        # он один на все модули, и `get_agents → True` ломает соседние чтения.
        multi_intent=True,
        attachments=[
            {"kind": "image", "name": "pic.png", "content": "на фото кот"},
            {"kind": "audio", "name": "voice.webm", "content": "привет это запись"},
        ],
    ):
        pass

    assert seen.get("fanout") == 2, "fan-out по вложениям не отработал"
    assert seen.get("called"), "вложения снова отменили декомпозицию"


# --------------------------------------------------------------------------- #
# T1.3 (аудит): usage под-шагов должен доходить до billing                     #
# --------------------------------------------------------------------------- #
def _complete_with_usage(prompt, completion, model):
    return AgentEvent(
        type=EventType.AGENT_COMPLETE,
        metadata={"token_usage": {"prompt": prompt, "completion": completion, "model": model}},
    )


@pytest.mark.asyncio
async def test_execute_steps_forwards_substep_usage_for_billing():
    """Регрессия аудита T1.3: usage под-шагов обязан дойти до ReplyAssembler.

    Раньше execute_steps глотал AGENT_COMPLETE под-агентов (нет ветки под этот тип), и из N
    под-агентских LLM-вызовов billing видел только финальный синтез → системный недобилл
    мульти-интента (масштаб = число подзадач).
    """
    from service.application.reply_assembler import ReplyAssembler

    step1 = _Agent([_chunk("шаг1"), _complete_with_usage(100, 50, "m-search")])
    step2 = _Agent([_chunk("шаг2"), _complete_with_usage(200, 80, "m-pptx")])
    synth = _Agent([_chunk("ИТОГ"), _complete_with_usage(30, 20, "m-general")])
    orch = _Orch({"web_search": step1, "pptx_gen": step2, "general": synth})
    subtasks = [
        SubTask(category="web_search", instruction="a"),
        SubTask(category="pptx_gen", instruction="b"),
    ]

    asm = ReplyAssembler()
    async for e in execute_steps(
        orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="q"
    ):
        asm.consume(
            event=e,
            stream_chunk_type=EventType.STREAM_CHUNK,
            error_type=EventType.ERROR,
            structured_output_type=EventType.STRUCTURED_OUTPUT,
        )

    # Пользователю стримится ТОЛЬКО синтез — контент под-шагов наружу не течёт.
    assert "".join(asm.reply_parts) == "ИТОГ"
    # Но usage посчитан по ВСЕМ трём вызовам (2 под-шага + синтез), а не только по синтезу.
    models = sorted(c["model"] for c in asm.per_call_usage)
    assert models == ["m-general", "m-pptx", "m-search"], f"под-шаги недосчитаны: {models}"
    assert asm.prompt_tokens == 100 + 200 + 30
    assert asm.completion_tokens == 50 + 80 + 20


# --------------------------------------------------------------------------- #
# P0.1 (аудит): артефакты под-шагов (картинка/pptx) не должны теряться          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_execute_steps_forwards_substep_artifacts():
    """Регрессия аудита P0.1: артефакт под-шага обязан дойти до ReplyAssembler.

    Раньше execute_steps копил только текст STREAM_CHUNK, а b64_json/pptx_b64 висящие в
    metadata глотал вместе с событием → пользователь платил за генерацию (usage
    ре-эмитился), но картинку/презентацию не получал. Теперь артефакт-метаданные
    пробрасываются наверх, воркер их персистит в file_url финального сообщения.
    """
    from service.application.reply_assembler import ReplyAssembler

    img_step = _Agent(
        [
            AgentEvent(
                type=EventType.STREAM_CHUNK,
                data="Готово — изображение сгенерировано.",
                metadata={"b64_json": "AAAA", "model": "img-model"},
            )
        ]
    )
    pptx_step = _Agent(
        [
            AgentEvent(
                type=EventType.STREAM_CHUNK,
                data="Презентация готова",
                metadata={"pptx_b64": "UEsD", "filename": "presentation.pptx"},
            )
        ]
    )
    synth = _Agent([_chunk("ИТОГ")])
    orch = _Orch({"image_gen": img_step, "pptx_gen": pptx_step, "general": synth})
    subtasks = [
        SubTask(category="image_gen", instruction="нарисуй"),
        SubTask(category="pptx_gen", instruction="сделай слайды"),
    ]

    asm = ReplyAssembler()
    async for e in execute_steps(
        orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="q"
    ):
        asm.consume(
            event=e,
            stream_chunk_type=EventType.STREAM_CHUNK,
            error_type=EventType.ERROR,
            structured_output_type=EventType.STRUCTURED_OUTPUT,
        )

    # Пользователю стримится ТОЛЬКО синтез — контент под-шагов наружу не течёт.
    assert "".join(asm.reply_parts) == "ИТОГ"
    # A4: оба артефакта дошли ОТДЕЛЬНЫМИ записями _pending_artifacts (воркер персистит
    # каждый в generated_files). Раньше singular b64_json/pptx_b64 клались в metadata и
    # разные ключи не конфликтовали — но ОДНОмодальные (2 картинки) затирали бы друг друга.
    pending = asm.metadata.get("_pending_artifacts") or []
    assert any(a.get("b64_json") == "AAAA" for a in pending), "картинка под-шага потеряна"
    assert any(
        a.get("pptx_b64") == "UEsD" and a.get("filename") == "presentation.pptx" for a in pending
    ), "презентация под-шага потеряна"
    # Singular-ключи в наружную metadata больше не течём (тяжёлый блоб).
    assert "b64_json" not in asm.metadata and "pptx_b64" not in asm.metadata


@pytest.mark.asyncio
async def test_multichunk_substep_persists_exactly_one_artifact():
    """Сквозной: длинный ответ под-шага даёт РОВНО ОДИН артефакт, а не по одному на чанк.

    ⚠️ Дублёры выше отдают по одному STREAM_CHUNK — и потому слепы к дефекту, который
    начинается со второго. Здесь под-шаг проходит через настоящий
    ``stream_text_chunks`` с настоящим текстом презентации: раньше ``pptx_b64``
    копировался в каждый чанк, сборщик клал артефакт из каждого события, и воркер
    персистил 2-3 ОДИНАКОВЫХ файла за одну генерацию.
    """
    from service.application.reply_assembler import ReplyAssembler
    from service.domain.subagents.base import BaseSubAgent

    class _RealPptxStep(BaseSubAgent):
        def __init__(self):
            super().__init__(name="pptx_gen", instructions="i", model_settings={"model": "m"})

        async def process(self, user_input, context):
            async for event in self.stream_text_chunks(
                "Слайд про квартальные результаты и планы. " * 40,
                metadata={"pptx_b64": "UEsD", "filename": "presentation.pptx"},
            ):
                yield event

    orch = _Orch({"pptx_gen": _RealPptxStep(), "general": _Agent([_chunk("ИТОГ")])})

    asm = ReplyAssembler()
    async for e in execute_steps(
        orchestrator=orch,
        subtasks=[SubTask(category="pptx_gen", instruction="сделай слайды")],
        context=_ctx(),
        user_input="q",
    ):
        asm.consume(
            event=e,
            stream_chunk_type=EventType.STREAM_CHUNK,
            error_type=EventType.ERROR,
            structured_output_type=EventType.STRUCTURED_OUTPUT,
        )

    pending = asm.metadata.get("_pending_artifacts") or []
    pptx = [a for a in pending if a.get("pptx_b64")]
    assert len(pptx) == 1, f"презентация персистилась бы {len(pptx)} раз(а) вместо одного"


@pytest.mark.asyncio
async def test_two_same_modality_artifacts_both_survive():
    """A4 (ядро): два шага ОДНОЙ модальности (2×image_gen) — оба артефакта уцелели.
    Раньше singular-ключ b64_json одного затирал другой при metadata.update → юзер
    платил за 2 картинки, получал 1."""
    from service.application.reply_assembler import ReplyAssembler

    img1 = _Agent(
        [AgentEvent(type=EventType.STREAM_CHUNK, data="кот", metadata={"b64_json": "IMG1"})]
    )
    img2 = _Agent(
        [AgentEvent(type=EventType.STREAM_CHUNK, data="собака", metadata={"b64_json": "IMG2"})]
    )
    synth = _Agent([_chunk("ИТОГ")])
    orch = _Orch({"image_gen": img1, "general": synth})
    # Обе подзадачи image_gen; get_agent вернёт img1 для обеих — поэтому кладём через
    # отдельные категории-алиасы не выйдет. Используем разные инстансы через прямой orch.
    orch._agents["image_gen"] = img1
    subtasks = [
        SubTask(category="image_gen", instruction="нарисуй кота"),
        SubTask(category="image_gen", instruction="нарисуй собаку"),
    ]

    # Чтобы два ОДНОмодальных шага реально дали два РАЗНЫХ артефакта, подменим get_agent:
    seq = iter([img1, img2])

    def _get_agent(name):
        return next(seq) if name == "image_gen" else synth

    orch.get_agent = _get_agent

    asm = ReplyAssembler()
    async for e in execute_steps(
        orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="q"
    ):
        asm.consume(
            event=e,
            stream_chunk_type=EventType.STREAM_CHUNK,
            error_type=EventType.ERROR,
            structured_output_type=EventType.STRUCTURED_OUTPUT,
        )

    pending = [a.get("b64_json") for a in (asm.metadata.get("_pending_artifacts") or [])]
    assert pending == ["IMG1", "IMG2"], f"одномодальные артефакты слиплись: {pending}"


# --------------------------------------------------------------------------- #
# B6 (аудит): синтез не дублирует результаты шагов в system_context             #
# --------------------------------------------------------------------------- #
class _RecordingAgent:
    """Под-агент, запоминающий последний (user_input, context) своего вызова."""

    def __init__(self, events):
        self._events = events
        self.seen: list[tuple[str, object]] = []

    async def process(self, user_input, context):
        self.seen.append((user_input, context))
        for e in self._events:
            yield e


@pytest.mark.asyncio
async def test_synthesis_context_not_double_injected():
    """Регрессия B6: результаты шагов лежат в synthesis-ПРОМПТЕ (user-сообщение).
    Раньше их ДУБЛИРОВАЛ ещё и _augment_context в system_context синтеза — двойная
    вставка + переполнение уже собранного под бюджет окна system_context. Теперь синтез
    получает базовый контекст без аугментации."""
    step1 = _Agent([_chunk("РЕЗУЛЬТАТ-ОДИН")])
    step2 = _Agent([_chunk("РЕЗУЛЬТАТ-ДВА")])
    synth = _RecordingAgent([_chunk("ИТОГ")])
    orch = _Orch({"web_search": step1, "pptx_gen": step2, "general": synth})
    # ЗАВИСИМЫЕ шаги (independent=False) → последовательный путь + синтез.
    subtasks = [
        SubTask(category="web_search", instruction="a"),
        SubTask(category="pptx_gen", instruction="b"),
    ]

    _ = [
        e
        async for e in execute_steps(
            orchestrator=orch, subtasks=subtasks, context=_ctx(), user_input="исходный запрос"
        )
    ]

    assert synth.seen, "синтез не вызывался"
    synth_input, synth_ctx = synth.seen[-1]
    sys_ctx = getattr(synth_ctx, "system_context", "") or ""

    # Результаты шагов — в ПРОМПТЕ синтеза (так модель их сведёт).
    assert "РЕЗУЛЬТАТ-ОДИН" in synth_input and "РЕЗУЛЬТАТ-ДВА" in synth_input
    # Но НЕ продублированы в system_context (иначе двойная вставка + переполнение).
    assert "РЕЗУЛЬТАТ-ОДИН" not in sys_ctx and "РЕЗУЛЬТАТ-ДВА" not in sys_ctx
    assert "Контекст предыдущих шагов" not in sys_ctx, "синтез снова аугментирует контекст (B6)"
    # Базовый собранный контекст при этом сохранён.
    assert sys_ctx == "BASE"


@pytest.mark.asyncio
async def test_augment_context_is_token_capped():
    """Промежуточный augment КЛАМПИТСЯ по токенам: system_context уже собран под
    бюджет окна, неограниченный augment его переполнял (аудит B6)."""
    from service.domain.pipeline import execution_plan as ep

    huge = "X" * 200_000  # ~50k токенов — заведомо больше потолка
    ctx = ep._augment_context(_ctx(), [("web_search", huge)])
    body = ctx.system_context or ""
    # Потолок ~4000 токенов → ~несколько десятков тысяч символов, но НЕ 200k.
    assert len(body) < 60_000, "augment не заклампился — риск переполнения окна"
    assert "ранние шаги обрезаны" in body


# --------------------------------------------------------------------------- #
# Оркестратор обходит regex-пре-фильтр                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_force_bypasses_the_conjunction_prefilter(monkeypatch):
    """🔴 Самый частый вид составного запроса пре-фильтр не ловил ВООБЩЕ.

    Он ищет союзы («затем», «потом», «;»), а «найди статистику и нарисуй по ней график»
    их не содержит — значит на таких запросах декомпозиция не запускалась никогда, и
    режим существовал только для формулировок со словом «затем».
    """
    from service.domain.pipeline import decomposition as dec

    seen = {"llm": 0}

    async def _models():
        return ["openai/gpt-4o-mini"]

    async def _completion(**_kw):
        seen["llm"] += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='[{"category":"web_search","instruction":"найти статистику"},'
                        '{"category":"image_gen","instruction":"нарисовать график"}]'
                    )
                )
            ],
            usage=None,
        )

    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)
    monkeypatch.setattr("service.domain.client.create_chat_completion", _completion)

    text = "найди статистику по продажам и нарисуй по ней график"
    assert dec.looks_multi_intent(text) is False, "пре-фильтр внезапно ловит этот текст"

    without = await dec.decompose_intents(text, model="openai/gpt-4o-mini")
    assert without is None and seen["llm"] == 0, "без force заплатили за заведомо пустой вызов"

    with_force = await dec.decompose_intents(text, model="openai/gpt-4o-mini", force=True)
    assert with_force is not None and len(with_force) == 2


@pytest.mark.asyncio
async def test_prefilter_still_saves_a_call_without_force(monkeypatch):
    """Без оркестратора пре-фильтр остаётся: он бесплатный и экономит вызов."""
    from service.domain.pipeline import decomposition as dec

    calls = {"n": 0}

    async def _models():
        calls["n"] += 1
        return ["m"]

    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)

    assert await dec.decompose_intents("расскажи про Париж", model="m") is None
    assert calls["n"] == 0
