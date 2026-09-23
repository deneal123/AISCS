"""P1.4 (аудит): спец-субагенты должны видеть собранный контекст пользователя.

Раньше web_search/deep_research/… читали только history_messages и игнорировали
system_context (память/знания/план), собранный пайплайном: follow-up «сравни это с
тем, что онлайн» уходил в веб без загруженного документа. Проверяем хелпер
BaseSubAgent.extra_user_context и его внедрение в синтез web_search.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.schemas.agents import UserContext


def _ctx(system_context=""):
    return UserContext(user_id="1", request_time=datetime.now(UTC), system_context=system_context)


# --------------------------------------------------------------------------- #
# BaseSubAgent.extra_user_context                                              #
# --------------------------------------------------------------------------- #
class _Dummy:
    def __init__(self):
        from service.domain.subagents.base import BaseSubAgent

        class _D(BaseSubAgent):
            def __init__(self):
                super().__init__(name="d", instructions="", model_settings={})

            async def process(self, user_input, context):  # pragma: no cover
                if False:
                    yield None

        self.agent = _D()


def test_extra_user_context_returns_trimmed_block():
    agent = _Dummy().agent
    out = agent.extra_user_context(_ctx("ФАКТ: пользователя зовут Данил."))
    assert "Данил" in out


def test_extra_user_context_empty_when_no_system_context():
    agent = _Dummy().agent
    assert agent.extra_user_context(_ctx("")) == ""


def test_extra_user_context_is_trimmed_to_budget():
    agent = _Dummy().agent
    big = "знание " * 5000
    out = agent.extra_user_context(_ctx(big), max_tokens=50)
    assert len(out) < len(big)  # реально обрезано


# --------------------------------------------------------------------------- #
# web_search-синтез внедряет контекст пользователя                             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_web_search_synthesis_includes_user_context(monkeypatch):
    import importlib

    import service.domain.client as client_mod
    import service.domain.subagents.context_query as cq
    from service.domain.subagents.web_search import WebSearchAgent

    # tools.web_search — и модуль, и функция в нём (пакет реэкспортит), поэтому берём
    # модуль через importlib, а не `import ... as` (иначе имя схлопывается на функцию).
    ws_tool = importlib.import_module("service.domain.tools.web_search")

    captured: dict = {}

    async def _models(*a, **k):
        return ["m"]

    async def _search(q, num_results=5):
        return [{"title": "T", "url": "http://x", "snippet": "S"}]

    async def _parse(url, max_chars=2000):
        return {}

    async def _standalone(ui, ctx, model, *, execution=None):
        return ui

    async def _create(**k):
        captured["messages"] = k["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ОТВЕТ"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _create)
    monkeypatch.setattr(ws_tool, "web_search", _search)
    monkeypatch.setattr(ws_tool, "parse_url", _parse)
    monkeypatch.setattr(cq, "build_standalone_query", _standalone)

    ctx = _ctx("ФАКТ: пользователя зовут Данил. ЗНАНИЕ: срок оплаты 45 дней.")
    agent = WebSearchAgent(model_settings={})
    _ = [e async for e in agent.process("сравни это с тем, что онлайн", ctx)]

    sys_msg = captured["messages"][0]["content"]
    assert "Контекст пользователя" in sys_msg
    assert "срок оплаты 45 дней" in sys_msg  # знание пользователя дошло до синтеза
