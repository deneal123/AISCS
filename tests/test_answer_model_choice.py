"""Текст, который читает пользователь, пишет ВЫБРАННАЯ им модель.

⚠️ Расхождение было тихим и не ловилось ничем. Субагенты звали ``pick_text_model`` —
функцию БЕЗ параметра предпочтения, — поэтому синтез веб-поиска, отчёт ресёрча,
содержимое презентации и постобработку расшифровки писала дешёвая модель по умолчанию.
Человек выбирал Opus, платил за ответ по прайсу gpt-4o-mini и получал текст от
gpt-4o-mini, нигде об этом не узнавая: учёт токенов был КОРРЕКТЕН, расходилось только
ожидание с реальностью — а это не видно ни в логах, ни в счёте.

Служебное остаётся на дешёвой намеренно: сжатие контекста — до 13 вызовов на секцию,
секций три, и на дорогой модели счёт вырос бы заметно за текст, которого пользователь
вообще не видит.
"""

from __future__ import annotations

import pytest

from service.domain.subagents.utils import pick_answer_model, pick_meta_model, pick_text_model

_USER_MODEL = "anthropic/claude-opus-4"
_AVAILABLE = ["openai/gpt-4o-mini", _USER_MODEL, "deepseek/deepseek-chat"]


def test_answer_model_prefers_the_user_choice():
    assert pick_answer_model(_AVAILABLE, _USER_MODEL) == _USER_MODEL


def test_answer_model_never_substitutes_an_unavailable_choice():
    """Ручной выбор не превращается в скрытый вызов другого провайдера."""
    assert pick_answer_model(["openai/gpt-4o-mini"], _USER_MODEL) is None


def test_answer_model_without_choice_is_the_cheap_default():
    assert pick_answer_model(_AVAILABLE, None) == "openai/gpt-4o-mini"


def test_meta_and_answer_agree_but_are_named_apart():
    """Логика одна, имена разные — и это осознанно: перепутать их значит перепутать деньги."""
    assert pick_meta_model(_AVAILABLE, _USER_MODEL) == pick_answer_model(_AVAILABLE, _USER_MODEL)


def test_plain_text_pick_still_ignores_preference():
    """⚠️ ``pick_text_model`` НЕ должен научиться предпочтению.

    Именно на нём держится дешёвое служебное: сжатие контекста, конденсация промпта
    картинки, разбор вложений. Дай ему параметр — и однажды кто-нибудь передаст туда
    выбор пользователя, а сжатие поедет по прайсу Opus.
    """
    import inspect

    assert list(inspect.signature(pick_text_model).parameters) == ["models"]


# --------------------------------------------------------------------------- #
# Сквозь настоящих субагентов                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("module", "cls"),
    [
        ("service.domain.subagents.web_search", "WebSearchAgent"),
        ("service.domain.subagents.deep_research", "DeepResearchAgent"),
        ("service.domain.subagents.pptx_generation", "PPTXGenerationAgent"),
        ("service.domain.subagents.audio_transcribe", "AudioTranscriptionAgent"),
    ],
)
def test_subagent_knows_the_user_model(module, cls):
    """Выбор пользователя доезжает до субагента и достаётся одинаково у всех."""
    import importlib

    agent = getattr(importlib.import_module(module), cls)({"model": _USER_MODEL})

    assert agent.preferred_model() == _USER_MODEL


def test_preferred_model_survives_absent_settings():
    """Настроек нет — не падаем: субагента могут создать и без выбора."""
    from service.domain.subagents.web_search import WebSearchAgent

    assert WebSearchAgent({}).preferred_model() is None


@pytest.mark.asyncio
async def test_web_search_synthesis_uses_the_user_model(monkeypatch):
    """Сквозной: синтез ответа уходит на модель пользователя, а не на дефолт."""
    import service.domain.client as client_mod
    from service.domain.subagents.web_search import WebSearchAgent
    from service.domain.tools import web_search as tools_ws

    seen: dict = {}

    async def _models():
        return _AVAILABLE

    async def _search(_q, num_results=5):
        return [{"url": "https://example.com/a", "title": "A", "snippet": "s"}]

    async def _parse(url, max_chars=2000):
        return {"content": "содержимое", "title": "t", "url": url}

    async def _completion(**kw):
        seen["model"] = kw.get("model")
        raise RuntimeError("дальше не нужно")

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _completion)
    monkeypatch.setattr(tools_ws, "web_search", _search)
    monkeypatch.setattr(tools_ws, "parse_url", _parse)

    agent = WebSearchAgent({"model": _USER_MODEL})
    [e async for e in agent.process("вопрос", None)]

    assert seen.get("model") == _USER_MODEL, (
        f"ответ писала {seen.get('model')}, а пользователь выбрал {_USER_MODEL}"
    )


@pytest.mark.asyncio
async def test_context_compression_stays_on_the_cheap_model(monkeypatch):
    """⚠️ Обратная сторона: служебное сжатие НЕ переехало на дорогую модель.

    Без этого теста «починку» можно было бы раскатать на все вызовы подряд, и тест
    выше остался бы зелёным — а счёт за запрос с крупным вложением вырос бы кратно.
    """
    import service.domain.client as client_mod
    from service.domain.pipeline import context_compressor as cc

    seen: dict = {}

    async def _models():
        return _AVAILABLE

    async def _completion(**kw):
        seen["model"] = kw.get("model")
        raise RuntimeError("дальше не нужно")

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _completion)
    monkeypatch.setattr(cc, "get_redis", lambda: None)

    await cc.compress_to_budget("очень длинный документ " * 2000, target=200, kind="files")

    assert seen.get("model") == "openai/gpt-4o-mini", (
        f"сжатие уехало на {seen.get('model')} — это до 13 вызовов на секцию"
    )
