"""Контракт тела ``/run`` (AgentRunInput) — сериализуемость + верность порту execute.

Готовит Фазу 4 (HttpAgentEngine сериализует этот DTO в POST /run, сайдкар разворачивает
в execute). Два инварианта:
1. DTO полностью JSON-round-trip'ится (в т.ч. tuple memory_parts восстанавливается);
2. поля DTO = подмножество параметров ``execute`` (иначе to_execute_kwargs сломает вызов),
   а несериализуемое (pseudo_session/on_event) в DTO НЕ попадает.
"""

from service.infrastructure.agents_client.contracts.run import AMBIENT_FIELDS, AgentRunInput
from service.infrastructure.agents_client.contracts.run import AgentRunInput as AgentRunInputDirect


def test_exported_from_schemas_package() -> None:
    assert AgentRunInput is AgentRunInputDirect


def test_agent_run_input_roundtrips_json() -> None:
    ri = AgentRunInput(
        text="привет",
        thread_id="t1",
        user_id="7",
        selected_model="openai:gpt-4o-mini",
        web_search=True,
        file_context="СОДЕРЖИМОЕ",
        attachments=[{"kind": "image", "name": "p.png", "content": "кот"}],
        memory_parts=("факты", "recall"),
        history_messages=[{"role": "user", "content": "прошлый вопрос"}],
        compact_summary="резюме диалога",
    )
    restored = AgentRunInput.model_validate_json(ri.model_dump_json())
    assert restored == ri
    # tuple переживает JSON (list) → обратно tuple — иначе execute(memory_parts=...) удивится
    assert restored.memory_parts == ("факты", "recall")
    assert isinstance(restored.memory_parts, tuple)


def test_unknown_fields_ignored_forward_compat() -> None:
    # backend новее сайдкара прислал лишнее поле — прогон НЕ должен падать.
    ri = AgentRunInput.model_validate({"text": "q", "thread_id": "t", "future_flag": 123})
    assert ri.text == "q" and not hasattr(ri, "future_flag")


def test_per_user_ldr_knobs_are_part_of_the_contract() -> None:
    """Per-user настройки LDR обязаны быть В КОНТРАКТЕ, иначе теряются молча.

    ⚠️ `HttpAgentEngine.execute` фильтрует kwargs по `AgentRunInput.model_fields`.
    Поле, дошедшее до воркера, но не объявленное здесь, не вызовет ошибки — оно
    просто НЕ УЕДЕТ в сайдкар. Для настроек ресёрча это значит: пользователь выбрал
    стратегию, интерфейс её показывает, а прогон идёт с дефолтной.
    """
    fields = AgentRunInput.model_fields
    assert "ldr_model" in fields
    assert "ldr_strategy" in fields
    ri = AgentRunInput(text="q", thread_id="t", ldr_strategy="focused-iteration")
    assert ri.to_execute_kwargs()["ldr_strategy"] == "focused-iteration"


def test_to_execute_kwargs_omits_transport_only_fields() -> None:
    kw = AgentRunInput(text="q", thread_id="t", memory_parts=("f", "r")).to_execute_kwargs()
    assert kw["text"] == "q" and kw["memory_parts"] == ("f", "r")
    # несериализуемое не участвует в теле → и в kwargs его нет
    assert "pseudo_session" not in kw and "on_event" not in kw


def test_to_execute_kwargs_omits_ambient_fields() -> None:
    """Окружение прогона едет в ТЕЛЕ, но НЕ аргументом движка.

    Снимок провайдерной политики разворачивает сторона исполнения (в ContextVar). Попади
    он в kwargs — execute упал бы на неизвестном аргументе, то есть сломался бы КАЖДЫЙ
    прогон в http-режиме.
    """
    ri = AgentRunInput(
        text="q", thread_id="t", provider_policy={"disabled": ["mws"], "blocked": []}
    )
    assert ri.provider_policy == {"disabled": ["mws"], "blocked": []}  # в теле — есть
    assert "provider_policy" not in ri.to_execute_kwargs()  # в аргументах — нет
    assert AMBIENT_FIELDS <= set(AgentRunInput.model_fields)
