"""P0.3 (аудит): служебные мета-вызовы должны тарифицироваться и идти на модели юзера.

Декомпозиция мульти-интента, оценка сложности и построение плана делают реальные
LLM-вызовы. Раньше их usage выбрасывался (системный недобилл, масштаб = число мета-
вызовов на запрос), а модель бралась произвольная дешёвая — не та, что выбрал юзер.
Теперь usage копится в usage_out, а модель предпочитается выбранная (если доступна).
"""

from types import SimpleNamespace

import pytest

import service.domain.client as client_mod
from service.domain.run_context import require_execution
from service.domain.subagents.utils import pick_meta_model


def _resp(content, prompt=40, completion=15):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
        ),
    )


# --------------------------------------------------------------------------- #
# pick_meta_model                                                              #
# --------------------------------------------------------------------------- #
def test_pick_meta_model_prefers_available_user_choice():
    assert pick_meta_model(["a", "user/model", "b"], "user/model") == "user/model"


def test_pick_meta_model_never_substitutes_an_unavailable_choice():
    assert pick_meta_model(["openai/gpt-4o-mini", "x"], "user/model") is None


def test_pick_meta_model_none_preferred_falls_back():
    assert pick_meta_model(["openai/gpt-4o-mini"], None) == "openai/gpt-4o-mini"


# --------------------------------------------------------------------------- #
# decompose_intents / assess_is_complex / build_plan — биллинг + модель юзера  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_decompose_bills_and_uses_user_model(monkeypatch):
    from service.domain.pipeline import decomposition

    async def _models(*a, **k):
        return ["user/model", "openai/gpt-4o-mini"]

    async def _create(**k):
        assert k["model"] == "user/model"  # выбор юзера, а не произвольный дефолт
        return _resp(
            '[{"category":"web_search","instruction":"a"},'
            '{"category":"pptx_gen","instruction":"b"}]'
        )

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _create)

    execution = require_execution()
    cursor = execution.usage.cursor()
    out = await decomposition.decompose_intents(
        "найди X, затем сделай презентацию", model="user/model", execution=execution
    )
    usage = execution.usage.project_since(cursor)
    assert [s.category for s in out] == ["web_search", "pdf_gen"]
    assert usage["model"] == "user/model"
    assert usage["prompt"] == 40 and usage["completion"] == 15


@pytest.mark.asyncio
async def test_complexity_bills_meta_call(monkeypatch):
    from service.domain.routing import complexity

    async def _models(*a, **k):
        return ["user/model"]

    async def _create(**k):
        return _resp('{"complexity":"complex"}')

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _create)

    execution = require_execution()
    cursor = execution.usage.cursor()
    # длинный неоднозначный запрос (>60 слов, без маркеров) → уходит в LLM-классификатор
    text = "слово " * 70
    result = await complexity.assess_is_complex(text, model="user/model", execution=execution)
    usage = execution.usage.project_since(cursor)
    assert result is True
    assert usage["completion"] == 15 and usage["model"] == "user/model"


@pytest.mark.asyncio
async def test_build_plan_bills_meta_call(monkeypatch):
    from service.domain.pipeline import planning

    async def _models(*a, **k):
        return ["user/model"]

    async def _create(**k):
        return _resp("1. шаг один\n2. шаг два")

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)
    monkeypatch.setattr(client_mod, "create_chat_completion", _create)

    execution = require_execution()
    cursor = execution.usage.cursor()
    plan, _events = await planning.build_plan(
        "реши сложную многошаговую задачу", model="user/model", execution=execution
    )
    usage = execution.usage.project_since(cursor)
    assert plan.strip()
    assert usage["prompt"] == 40 and usage["model"] == "user/model"
