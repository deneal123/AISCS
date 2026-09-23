import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from service.domain.routing.explicit_intent import explicit_requested_tool
from service.domain.tools.router import (
    SelectedModelUnavailable,
    _parse_llm_response,
    _pick_router_model,
    route_model,
)

# ── Unit: helpers ─────────────────────────────────────────────────────────────


def test_pick_router_model_prefers_small():
    models = ["qwen3-235b-alpha", "qwen3-8b-instruct", "mws-gpt-alpha"]
    assert _pick_router_model(models) == "qwen3-8b-instruct"


def test_pick_router_model_falls_back_to_text_family():
    models = ["mws-gpt-alpha", "some-unknown-model"]
    assert _pick_router_model(models) == "mws-gpt-alpha"


def test_parse_llm_response_valid():
    raw = '{"model": "qwen3-32b", "tool": "web_search", "reason": "needs live data"}'
    result = _parse_llm_response(raw, ["qwen3-32b", "other"])
    assert result["model"] == "qwen3-32b"
    assert result["tool"] == "web_search"
    assert result["reason"] == "needs live data"


def test_parse_llm_response_strips_markdown():
    raw = '```json\n{"model": "qwen3-32b", "tool": "none", "reason": "ok"}\n```'
    result = _parse_llm_response(raw, ["qwen3-32b"])
    assert result["model"] == "qwen3-32b"


def test_parse_llm_response_drops_hallucinated_model():
    raw = '{"model": "gpt-9000-turbo", "tool": "none", "reason": "nope"}'
    result = _parse_llm_response(raw, ["qwen3-32b", "llama-3"])
    assert result["model"] is None


def test_parse_llm_response_sanitizes_invalid_tool():
    raw = '{"model": "qwen3-32b", "tool": "INVALID", "reason": "x"}'
    result = _parse_llm_response(raw, ["qwen3-32b"])
    assert result["tool"] == "none"


def test_parse_llm_response_migrates_pptx_gen_to_pdf_gen():
    raw = '{"model": "qwen3-32b", "tool": "pptx_gen", "reason": "slides requested"}'
    result = _parse_llm_response(raw, ["qwen3-32b"])
    assert result["tool"] == "pdf_gen"


def test_parse_llm_response_accepts_audio_transcribe():
    raw = '{"model": "qwen3-32b", "tool": "audio_transcribe", "reason": "audio to text"}'
    result = _parse_llm_response(raw, ["qwen3-32b"])
    assert result["tool"] == "audio_transcribe"


def test_guard_tool_modality_drops_audio_without_audio_input():
    from service.domain.tools.router import _guard_tool_modality

    # audio_transcribe без аудио-входа → none (иначе .md/документ ушёл бы на ASR)
    assert _guard_tool_modality("audio_transcribe", "text") == "none"
    assert _guard_tool_modality("audio_transcribe", None) == "none"
    # при реальном аудио — остаётся; прочие инструменты не трогаем
    assert _guard_tool_modality("audio_transcribe", "audio") == "audio_transcribe"
    assert _guard_tool_modality("web_search", "text") == "web_search"


# ── Integration: manual override (no API needed) ─────────────────────────────


def test_route_model_keeps_manual_if_available():
    model, meta = asyncio.run(
        route_model(
            text="hello",
            selected_model="qwen3-32b",
            input_type="text",
            available_models=["qwen3-32b", "mws-gpt-alpha"],
        )
    )
    assert model == "qwen3-32b"
    assert meta.get("source") == "manual"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('создай PDF файл, в котором напиши "тест"', "pdf_gen"),
        ("Напиши по прикрепленным материалам обзорную статью в PDF", "pdf_gen"),
        ("prepare a Beamer presentation", "pdf_gen"),
        ("расскажи, чем PDF отличается от Markdown", None),
        ("проверь эту статью", None),
    ],
)
def test_explicit_document_route_requires_creation_action(text, expected):
    assert explicit_requested_tool(text) == expected


def test_manual_model_keeps_exact_model_and_exposes_explicit_document_route():
    model, meta = asyncio.run(
        route_model(
            text="Напиши по прикрепленным материалам статью в PDF",
            selected_model="GigaChat-3-Lightning",
            input_type="text",
            available_models=["GigaChat-3-Lightning", "openai/gpt-4o"],
        )
    )

    assert model == "GigaChat-3-Lightning"
    assert meta == {
        "requested_model": "GigaChat-3-Lightning",
        "available_models_count": 2,
        "input_type": "text",
        "tool": "pdf_gen",
        "source": "manual",
    }


def test_route_model_never_accepts_manual_model_without_admission_evidence():
    with (
        patch(
            "service.domain.client.list_qualified_models",
            new=AsyncMock(return_value=[]),
        ),
        pytest.raises(SelectedModelUnavailable),
    ):
        asyncio.run(
            route_model(
                text="hello",
                selected_model="GigaChat-3-Lightning",
                input_type="text",
                available_models=[],
            )
        )


# ── A2 (аудит): usage роутер-LLM отдаётся наверх для тарификации ──────────────


def test_llm_route_accumulates_usage():
    """Роутер — реальный провайдерский вызов; его usage раньше выбрасывался (недобилл)."""
    from types import SimpleNamespace

    from service.domain.tools.router import _llm_route

    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"model": "m1", "tool": "none", "reason": "ok"}')
            )
        ],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=15, total_tokens=135),
    )
    from service.domain.run_context import RunExecutionContext

    execution = RunExecutionContext()
    with patch(
        "service.domain.client.create_chat_completion",
        new=AsyncMock(return_value=resp),
    ):
        result = asyncio.run(_llm_route("запрос", ["m1", "m2"], "m1", None, execution))
    assert result["model"] == "m1"
    # usage посчитан с моделью роутера (без неё цена ушла бы в дефолт).
    assert execution.usage.prompt_tokens == 120
    assert execution.usage.completion_tokens == 15
    assert len(execution.usage.receipts) == 1
    assert execution.usage.receipts[0].kind == "route_model"


def test_route_model_manual_leaves_usage_empty():
    """В ручном режиме роутер-LLM не зовётся → usage_out пуст (тарифицировать нечего)."""
    from service.domain.run_context import RunExecutionContext

    execution = RunExecutionContext()
    _model, meta = asyncio.run(
        route_model(
            text="hello",
            selected_model="qwen3-32b",
            input_type="text",
            available_models=["qwen3-32b", "mws-gpt-alpha"],
            execution=execution,
        )
    )
    assert meta.get("source") == "manual"
    assert execution.usage.receipts == ()


# ── Integration: LLM router (mocked via _llm_route) ──────────────────────────


def test_route_model_uses_llm_router_result():
    llm_result = {"model": "qwen3-coder-480b-a35b", "tool": "none", "reason": "code task"}

    with patch(
        "service.domain.tools.router._llm_route",
        new=AsyncMock(return_value=llm_result),
    ):
        model, meta = asyncio.run(
            route_model(
                text="fix this python bug",
                selected_model=None,
                input_type=None,
                available_models=["qwen3-8b-instruct", "qwen3-coder-480b-a35b"],
            )
        )

    assert model == "qwen3-coder-480b-a35b"
    assert meta["source"] == "llm"
    assert meta["tool"] == "none"
    assert "reason" in meta


def test_route_model_llm_receives_input_type():
    """input_type is passed through as-is (it's a fact, not a prediction)."""
    llm_result = {"model": "qwen-vl-72b", "tool": "none", "reason": "image analysis with VLM"}

    with patch(
        "service.domain.tools.router._llm_route",
        new=AsyncMock(return_value=llm_result),
    ) as mock:
        model, meta = asyncio.run(
            route_model(
                text="что на этой картинке?",
                selected_model=None,
                input_type="image",
                available_models=["qwen3-8b-instruct", "qwen-vl-72b"],
            )
        )

    # input_type is passed through to metadata from the request, not from LLM
    assert meta["input_type"] == "image"
    assert meta["source"] == "llm"
    assert model == "qwen-vl-72b"

    # Verify _llm_route received input_type as an argument
    mock.assert_called_once()
    call_kwargs = mock.call_args
    assert call_kwargs[0][3] == "image"  # 4th positional arg = input_type


def test_route_model_llm_auto_web_search():
    llm_result = {"model": "mws-gpt-alpha", "tool": "web_search", "reason": "needs live data"}

    with patch(
        "service.domain.tools.router._llm_route",
        new=AsyncMock(return_value=llm_result),
    ):
        model, meta = asyncio.run(
            route_model(
                text="какой курс доллара сейчас?",
                selected_model=None,
                input_type=None,
                available_models=["qwen3-8b-instruct", "mws-gpt-alpha"],
            )
        )

    assert meta["tool"] == "web_search"
    assert meta["source"] == "llm"
    assert model == "mws-gpt-alpha"


def test_route_model_llm_migrates_pptx_gen():
    llm_result = {"model": "mws-gpt-alpha", "tool": "pptx_gen", "reason": "presentation requested"}

    with patch(
        "service.domain.tools.router._llm_route",
        new=AsyncMock(return_value=llm_result),
    ):
        model, meta = asyncio.run(
            route_model(
                text="сделай презентацию про ИИ",
                selected_model=None,
                input_type=None,
                available_models=["qwen3-8b-instruct", "mws-gpt-alpha"],
            )
        )

    assert meta["tool"] == "pdf_gen"
    assert meta["source"] == "llm"


def test_route_model_llm_audio_transcribe_dropped_for_non_audio():
    """Регресс на баг маршрутизации: LLM «угадал» audio_transcribe для текстового
    сообщения (приложен .md + «вот файл») — модальный гард сбрасывает инструмент
    в none, чтобы файл не ушёл на ASR-агент (echo вместо анализа)."""
    llm_result = {"model": "mws-gpt-alpha", "tool": "audio_transcribe", "reason": "guessed"}

    with patch(
        "service.domain.tools.router._llm_route",
        new=AsyncMock(return_value=llm_result),
    ):
        model, meta = asyncio.run(
            route_model(
                text="вот файл",
                selected_model=None,
                input_type="text",
                available_models=["qwen3-8b-instruct", "mws-gpt-alpha"],
            )
        )

    assert meta["tool"] == "none"
    assert meta["source"] == "llm"


def test_route_model_llm_audio_transcribe_kept_for_audio_input():
    """При реальном аудио-входе audio_transcribe сохраняется — гард не мешает ASR."""
    llm_result = {"model": "mws-gpt-alpha", "tool": "audio_transcribe", "reason": "audio"}

    with patch(
        "service.domain.tools.router._llm_route",
        new=AsyncMock(return_value=llm_result),
    ):
        model, meta = asyncio.run(
            route_model(
                text="распознай речь",
                selected_model=None,
                input_type="audio",
                available_models=["qwen3-8b-instruct", "mws-gpt-alpha"],
            )
        )

    assert meta["tool"] == "audio_transcribe"


# ── Integration: regex fallback when LLM returns None ────────────────────────


def test_route_model_regex_fallback_on_llm_failure():
    with patch("service.domain.tools.router._llm_route", new=AsyncMock(return_value=None)):
        model, meta = asyncio.run(
            route_model(
                text="```python\nimport os\nprint('hi')\n```\nfix bug",
                selected_model=None,
                input_type="text",
                available_models=["mws-gpt-alpha", "qwen3-coder-480b-a35b"],
            )
        )

    # Курируемый шорт-лист надёжных моделей отсекает необлайстленный
    # qwen3-coder-480b-a35b: код уходит на надёжную mws-gpt-alpha, а не на экзотику
    # агрегатора (которая склонна к timeout). Детект кода при этом сохраняется.
    assert model == "mws-gpt-alpha"
    assert meta["source"] == "regex_fallback"
    assert meta.get("text_kind") == "code"


def test_route_model_regex_fallback_image_input_type():
    with patch("service.domain.tools.router._llm_route", new=AsyncMock(return_value=None)):
        model, meta = asyncio.run(
            route_model(
                text="analyze attached image",
                selected_model=None,
                input_type="image",
                available_models=["mws-gpt-alpha", "qwen-image"],
            )
        )

    assert model == "qwen-image"
    assert meta.get("input_type") == "image"
    assert meta["source"] == "regex_fallback"


def test_route_model_regex_fallback_audio_input_type_sets_audio_tool():
    with patch("service.domain.tools.router._llm_route", new=AsyncMock(return_value=None)):
        model, meta = asyncio.run(
            route_model(
                text="распознай речь из аудио",
                selected_model=None,
                input_type="audio",
                available_models=["mws-gpt-alpha", "qwen3-8b-instruct"],
            )
        )

    assert model in {"mws-gpt-alpha", "qwen3-8b-instruct"}
    assert meta.get("tool") == "audio_transcribe"
    assert meta["source"] == "regex_fallback"


def test_route_model_regex_fallback_high_complexity():
    with patch("service.domain.tools.router._llm_route", new=AsyncMock(return_value=None)):
        text = "\n".join(
            [
                "Design an architecture with constraints and edge cases.",
                "Must optimize performance and reliability.",
                "Need pipeline design and fallback strategy.",
                "Include migration plan and rollback policy.",
                "Consider observability and testing strategy.",
                "Add security constraints and compliance controls.",
            ]
        )
        model, meta = asyncio.run(
            route_model(
                text=text,
                selected_model=None,
                input_type="text",
                available_models=["llama-3.1-8b-instruct", "Qwen3-235B-A22B-Instruct-2507-FP8"],
            )
        )

    assert model == "Qwen3-235B-A22B-Instruct-2507-FP8"
    assert meta.get("complexity") in {"medium", "high"}
    assert meta["source"] == "regex_fallback"


# --------------------------------------------------------------------------- #
# Два списка «непригодных моделей» — разделение обязанностей, а не расхождение   #
# --------------------------------------------------------------------------- #
def test_router_blocklist_is_a_subset_of_registry():
    """⚠️ Список роутера КОРОЧЕ реестрового намеренно — но обязан быть его частью.

    Вопросы у них разные: реестр отвечает «может ли модель вести ТЕКСТОВЫЙ диалог» и
    блокирует генераторы картинок/видео; роутер строит пул КАНДИДАТОВ и сам
    маршрутизирует в `image`/`video` — отфильтруй он их, и запрос с картинкой ушёл бы
    текстовой модели (это ловит соседний тест `..._image_input_type`).

    Разница выглядела случайной ровно до тех пор, пока её никто не назвал: короткий
    список читается как «забыли дописать», и «исправление» ломает маршрутизацию
    картинок. Здесь фиксируется ОТНОШЕНИЕ: маркер, которого реестр не знает, — это уже
    расхождение, а не разделение обязанностей.
    """
    from service.domain.client.registry import _BLOCKED_MODEL_MARKERS
    from service.domain.tools.router import _ROUTER_BLOCKED_MARKERS

    # ⚠️ Сравнение по ВХОЖДЕНИЮ, а не по равенству множеств: оба списка применяются как
    # `marker in model_id.lower()`. Реестр блокирует `speech`, роутер — `speech-to-text`;
    # буквально это разные строки, но реестр строго шире. Проверка на равенство падала
    # бы на таком и толкала «выровнять» списки, то есть сломать ровно то, что здесь
    # защищается.
    uncovered = [
        marker
        for marker in _ROUTER_BLOCKED_MARKERS
        if not any(known in marker for known in _BLOCKED_MODEL_MARKERS)
    ]

    assert not uncovered, f"роутер блокирует то, чего реестр не знает: {uncovered}"


def test_router_keeps_image_and_video_models_as_candidates():
    """Обратная сторона: генеративные модальности из пула НЕ вычищаются.

    Иначе `input_type="image"` не нашёл бы кандидата и ушёл бы в текстовую ветку.
    """
    from service.domain.tools.router import _normalize_models

    pool = _normalize_models(["qwen-image", "flux-1.1-pro", "sora-2", "text-embedding-3"])

    assert "qwen-image" in pool and "flux-1.1-pro" in pool and "sora-2" in pool
    assert "text-embedding-3" not in pool, "эмбеддинг не годится ни под один маршрут"
