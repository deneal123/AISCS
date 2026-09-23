"""Примеси путей исполнения получают от класса-хозяина всё, что им нужно.

⚠️ ЦЕНА ПРИМЕСИ — НЕЯВНЫЙ КОНТРАКТ. `SdkRunMixin` и `ChatRunMixin` обращаются к
`self.name`, `self.tools`, `self._build_messages` и ещё десятку имён, которых у них
самих нет. Пока оба пути лежали внутри `SimpleStreamingAgent`, это были обычные методы
одного класса; после разделения зависимость стала невидимой — и её легко порвать,
переименовав атрибут в хозяине.

Ломается это ХУЖЕ, чем обычная опечатка: `AttributeError` вылезет не на импорте и не в
конструкторе, а В СЕРЕДИНЕ ПРОГОНА агента — то есть после того, как пользователь уже
отправил сообщение и списаны токены за роутинг.

Поэтому состав перечислен явно и проверяется здесь.
"""

from __future__ import annotations

import inspect
import re

from service.domain.base import SimpleStreamingAgent
from service.domain.runners import ChatRunMixin, SdkRunMixin

# Что примеси берут у хозяина. Списки ведутся вручную — они же выписаны в докстрингах
# самих примесей, и расхождение между «объявлено» и «используется» ловит тест ниже.
SDK_REQUIRES = {
    "name",
    "instructions",
    "tools",
    "model_settings",
    "max_turns",
    "input_guardrails",
    "output_guardrails",
    "_compose_system_instructions",
    "_build_input_items",
    "_is_blocked_chat_model",
    "_pick_chat_capable_model",
}
CHAT_REQUIRES = {
    "name",
    "instructions",
    "tools",
    "model_settings",
    "_build_messages",
    "_resolve_chat_model",
    "_resolve_toolset",
    "_build_tool_context",
}


def _agent() -> SimpleStreamingAgent:
    return SimpleStreamingAgent(name="general", instructions="x", model_settings={})


def test_host_provides_everything_the_mixins_need():
    """Каждое объявленное имя реально есть у собранного агента."""
    agent = _agent()
    missing = sorted(n for n in SDK_REQUIRES | CHAT_REQUIRES if not hasattr(agent, n))

    assert not missing, f"примеси обратятся к несуществующим именам В СЕРЕДИНЕ прогона: {missing}"


def test_declared_requirements_cover_what_is_actually_used():
    """⚠️ Обратная сторона: список требований не должен отставать от кода.

    Иначе он превращается в устаревший комментарий: примесь тянет новое имя, список
    молчит, и первый же переименованный атрибут ломает прогон. Сверяем со всеми
    `self.<имя>`, которые примесь реально упоминает.
    """
    for mixin, declared in ((SdkRunMixin, SDK_REQUIRES), (ChatRunMixin, CHAT_REQUIRES)):
        source = inspect.getsource(mixin)
        used = set(re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)", source))
        # Имена, определённые в самой примеси, хозяину предъявлять незачем.
        own = {n for n, _ in inspect.getmembers(mixin) if not n.startswith("__")}
        undeclared = sorted(used - declared - own)

        assert not undeclared, (
            f"{mixin.__name__} берёт у хозяина необъявленное: {undeclared} — "
            "допишите в список требований и в докстринг примеси"
        )


def test_both_paths_are_reachable_from_the_agent():
    """Диспетчер `process()` умеет позвать оба пути — примеси действительно подключены."""
    agent = _agent()

    assert callable(agent._run_sdk_streamed)
    assert callable(agent._run_chat_streamed)
    assert isinstance(agent, SdkRunMixin) and isinstance(agent, ChatRunMixin)
