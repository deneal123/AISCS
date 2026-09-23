"""Единый usage-контур прогона (`service/domain/usage_tracking.py`).

Регрессия: субагенты обязаны писать МОДЕЛЬ в token_usage — иначе биллинг считает по
ДЕФОЛТ-цене (resolve_model_price(None)) вместо реальной. Раньше _accumulate_usage был
скопирован в 4 субагента; теперь единый helper, его и проверяем.
"""

from types import SimpleNamespace

from service.domain.legacy_usage import accumulate_usage
from service.domain.usage_tracking import build_token_usage_meta


def _resp(prompt: int = 10, completion: int = 20):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
        )
    )


def test_accumulate_records_model_and_tokens() -> None:
    acc: dict = {}
    accumulate_usage(acc, _resp(), "gpt-4o-mini")
    assert acc["model"] == "gpt-4o-mini"
    assert (acc["prompt"], acc["completion"], acc["total"]) == (10, 20, 30)


def test_accumulate_sums_across_calls_last_model_wins() -> None:
    acc: dict = {}
    accumulate_usage(acc, _resp(10, 20), "m1")
    accumulate_usage(acc, _resp(5, 5), "m2")
    assert acc["total"] == 40
    assert acc["model"] == "m2"  # последняя реальная модель перебивает


def test_accumulate_without_model_leaves_key_unset() -> None:
    acc: dict = {}
    accumulate_usage(acc, _resp())
    assert "model" not in acc  # None не затирает — поздний вызов с моделью выиграет


def test_accumulate_none_usage_out_is_noop() -> None:
    accumulate_usage(None, _resp(), "m")  # не должно падать


def test_accumulate_response_without_usage_is_noop() -> None:
    acc: dict = {}
    accumulate_usage(acc, SimpleNamespace(usage=None), "m")
    assert acc == {}


def test_build_token_usage_meta_surfaces_model() -> None:
    meta = build_token_usage_meta({"prompt": 10, "completion": 20, "total": 30, "model": "m-real"})
    assert meta is not None
    assert meta["token_usage"]["model"] == "m-real"


def test_build_token_usage_meta_none_when_empty() -> None:
    assert build_token_usage_meta({}) is None


# --------------------------------------------------------------------------- #
# image_gen: кастомный _usage_meta поверх общего base (фикс-эквивалент)        #
# --------------------------------------------------------------------------- #
def test_image_usage_meta_fixed_equivalent_when_generated_without_usage() -> None:
    from service.domain.subagents.image_generation import ImageGenerationAgent

    # P1.5: фикс-эквивалент обязан нести МОДЕЛЬ, иначе resolve_model_price(None) уходит
    # в дефолт-цену вместо цены image-модели (картинка тарифилась по чужому тарифу).
    meta = ImageGenerationAgent._usage_meta({}, image_generated=True, model="dall-e-3")
    assert meta is not None
    assert meta["token_usage"]["estimated"] is True
    assert meta["token_usage"]["total"] == 1024
    assert meta["token_usage"]["model"] == "dall-e-3"


def test_image_usage_meta_prefers_real_usage() -> None:
    from service.domain.subagents.image_generation import ImageGenerationAgent

    meta = ImageGenerationAgent._usage_meta(
        {"prompt": 5, "completion": 5, "total": 10, "model": "img"}, image_generated=True
    )
    assert meta["token_usage"]["model"] == "img"
    assert "estimated" not in meta["token_usage"]


def test_tools_use_the_ledger_native_model_runtime():
    """Model calls create receipts at invocation, not in mutable callers."""
    import inspect

    from service.domain.subagents.research import planner as research_planner
    from service.domain.subagents.research import synthesis as research_synthesis
    from service.domain.tools import pptx as tools_pptx

    for module in (tools_pptx,):
        source = inspect.getsource(module)
        assert "def _accumulate_usage(" not in source, f"копия вернулась в {module.__name__}"
        assert "invoke_model_call(" in source
        assert "execution=execution" in source
        assert "usage_out" not in source
    for module in (research_planner, research_synthesis):
        source = inspect.getsource(module)
        assert "invoke_model_call(" in source
        assert ".run_model(" in source
