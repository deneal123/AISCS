"""Шаг, ответивший СТРУКТУРОЙ, доезжает до синтеза.

⚠️ Зачем файл, если этот тип события сегодня не эмитит никто. Единственным источником
был `CollectorGeneratorAgent` — класс, который не инстанцировался нигде и удалён. Ветка
разбора осталась намеренно: `structured_output` объявлен в контракте событий, который
сверяется с backend'ом парити-гейтом, зеркалится в его `contracts/events.py` и имеет
ярлык на фронте. То есть протокол разрешает такое событие, и следующий агент, который
начнёт его слать, обязан работать сразу. Без теста ветка выглядит ровно как мёртвый код
и будет удалена следующим же проходом за мёртвым кодом.

⚠️ ПРОВЕРЯТЬ НУЖНО ПРОМПТ СИНТЕЗА, А НЕ ВЫДАННЫЕ СОБЫТИЯ. Первая версия этого файла
собирала `data` из событий `execute_steps` — и была ФАЛЬШИВОЙ: все три мутации (снести
ветку, `ensure_ascii=True`, убрать защиту от None) оставались зелёными. Причина в том,
что `_run_one_step` результат шага СОБИРАЕТ и наружу не йелдит («контент шага наружу не
течёт — стримит синтез»), а полезная нагрузка появлялась в выводе совсем по другому
пути: фейковый агент повторно отдавал то же событие уже на синтезе, и оно проходило
насквозь. Тест мерил пропускание событий вместо сворачивания структуры.
"""

from __future__ import annotations

import pytest

from service.domain.pipeline import execution_plan
from service.domain.pipeline.decomposition import SubTask
from service.events import AgentEvent, EventType


async def _synthesis_prompt_for(step_events: list[AgentEvent]) -> str:
    """Прогнать один шаг и вернуть промпт, с которым позвали синтез.

    Шаг отдаёт `step_events`; синтез (второй и последующие вызовы) отвечает обычным
    чанком, чтобы его выход не подмешивался в проверку.
    """
    prompts: list[str] = []

    class _Agent:
        name = "general"

        async def process(self, user_input, context):
            prompts.append(str(user_input))
            if len(prompts) == 1:  # первый вызов — сам шаг
                for e in step_events:
                    yield e
                return
            yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="итог")

    class _Orch:
        def get_agent(self, _name):
            return _Agent()

    async for _ in execution_plan.execute_steps(
        orchestrator=_Orch(),
        subtasks=[SubTask(category="general", instruction="шаг")],
        context=None,
        user_input="запрос",
    ):
        pass

    assert len(prompts) >= 2, "синтез не вызывался — предпосылка теста неверна"
    return prompts[-1]


def _structured(payload):
    return [AgentEvent(type=EventType.STRUCTURED_OUTPUT, agent_name="general", data=payload)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        ("готовый текст", "готовый текст"),
        ({"итог": "значение"}, '"значение"'),
        ([1, 2, 3], "[1, 2, 3]"),
    ],
    ids=["строка", "словарь", "список"],
)
async def test_structured_output_reaches_synthesis(payload, needle):
    """Структура сворачивается в текст: строка как есть, остальное — JSON."""
    prompt = await _synthesis_prompt_for(_structured(payload))

    assert needle in prompt, f"структурный вывод шага не доехал до синтеза: {prompt!r}"
    assert "не выполнен" not in prompt, "шаг со структурным выводом посчитан проваленным"


@pytest.mark.asyncio
async def test_json_is_not_escaped_to_unicode():
    r"""⚠️ `ensure_ascii=False`: иначе в синтез уедет За... вместо кириллицы."""
    prompt = await _synthesis_prompt_for(_structured({"город": "Москва"}))

    assert "Москва" in prompt
    assert "\\u" not in prompt, "кириллица ушла в синтез экранированной"


@pytest.mark.asyncio
async def test_none_payload_is_not_folded_in():
    """`data is None` — не результат, в промпт синтеза он попасть не должен.

    ⚠️ Проверяем И «null». Без защиты `event.data is not None` ветка отработает на None:
    `isinstance(None, str)` ложно, значит уйдёт в `json.dumps(None)` — а это **"null"**,
    не «None». Первая версия проверки искала только «None», поэтому снятие защиты её не
    роняло: синтез получал бы шаг с результатом «null» и добросовестно пересказывал его
    как содержательный ответ.
    """
    prompt = await _synthesis_prompt_for(_structured(None))

    assert "None" not in prompt
    assert "null" not in prompt, "пустой структурный вывод уехал в синтез как «null»"


@pytest.mark.asyncio
async def test_step_without_any_output_is_reported_as_failed():
    """Контроль предпосылки: пустой шаг ДЕЙСТВИТЕЛЬНО даёт «[Шаг не выполнен]».

    Без этого проверки выше не доказывают, что сворачивание что-то меняет: надо знать,
    как выглядит промпт, когда шаг не дал ничего.
    """
    prompt = await _synthesis_prompt_for(
        [AgentEvent(type=EventType.ERROR, agent_name="general", data="агент упал")]
    )

    assert "не выполнен" in prompt
