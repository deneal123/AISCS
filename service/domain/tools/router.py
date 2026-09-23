from __future__ import annotations

import json
import logging
import re
from typing import Literal

from service.domain.capabilities import modality_conflict, valid_router_tools
from service.domain.json_fence import strip_json_fence
from service.domain.llm_response import first_message_content
from service.domain.routing.explicit_intent import explicit_requested_tool
from service.domain.routing.policy import canonical_route

logger = logging.getLogger(__name__)

InputType = Literal["text", "image", "audio", "video"]

_TEXT_FAMILY_RE = re.compile(
    r"(gpt|qwen|llama|mistral|gemma|deepseek|yi|phi|glm|kimi|instruct|chat|alpha|gigachat)", re.I
)
_CODE_FAMILY_RE = re.compile(
    r"(kodify|code|coder|codestral|starcoder|deepseek.*coder|qwen.*coder)", re.I
)
_IMAGE_FAMILY_RE = re.compile(r"(image|vision|vl|multimodal|dall-e|sdxl|flux)", re.I)
_VIDEO_FAMILY_RE = re.compile(r"(video|vision|vl|multimodal)", re.I)
_LARGE_MODEL_RE = re.compile(r"(357b|235b|120b|70b|72b|480b|pro|alpha|gigachat-max)", re.I)
_SMALL_MODEL_RE = re.compile(r"(8b|20b|lightning|mini|small)", re.I)
_FAST_MODEL_RE = re.compile(r"(8b|7b|4b|3b|mini|small|lite|flash|lightning|fast)", re.I)


class SelectedModelUnavailable(RuntimeError):
    """A manual choice is not admitted for this run; never substitute another model."""


# ⚠️ СПИСОК КОРОЧЕ, ЧЕМ В РЕЕСТРЕ (`client/registry._BLOCKED_MODEL_MARKERS`, 35 имён),
# И ЭТО НАМЕРЕННО. Вопросы разные:
#
#   * реестр отвечает «может ли модель вести ТЕКСТОВЫЙ диалог» и потому блокирует
#     генераторы картинок и видео;
#   * здесь строится пул КАНДИДАТОВ роутера, а роутер сам маршрутизирует в
#     `image`/`video` (см. `_IMAGE_FAMILY_RE`, `_VIDEO_FAMILY_RE`). Отфильтруй он их —
#     и запрос с картинкой уходил бы текстовой модели.
#
# Оставлено ровно то, что не годится НИ ПОД ОДИН маршрут: эмбеддинги, реранкеры и
# распознавание/синтез речи. Соотношение «здесь ⊂ в реестре» держит тест
# `test_router_blocklist_is_a_subset_of_registry`: если сюда попадёт маркер, которого
# реестр не знает, это уже расхождение, а не разделение обязанностей.
_ROUTER_BLOCKED_MARKERS = (
    "bge",
    "e5",
    "gte",
    "embed",
    "embedding",
    "rerank",
    "ranker",
    "whisper",
    "asr",
    "stt",
    "tts",
    "speech-to-text",
    "text-to-speech",
)


def _is_chat_capable_model(model_id: str | None) -> bool:
    """Годится ли модель В КАНДИДАТЫ роутера (не «годится ли для чата» — см. выше)."""
    low = str(model_id or "").strip().lower()
    if not low:
        return False
    return not any(marker in low for marker in _ROUTER_BLOCKED_MARKERS)


_ROUTER_SYSTEM = """\
Ты — высокоточный роутер GPTHub.
Вход: сообщение пользователя, модальности и список доступных ID моделей.
Цель: выбрать лучшую модель и один инструментальный маршрут с минимальным числом ошибок.

Верни РОВНО один JSON-объект, без markdown и комментариев:
{"model":"<точный id>","tool":"none|general|web_search|deep_research|audio_transcribe|image_gen|pdf_gen","reason":"<до 12 слов>"}

Жёсткие ограничения:
1) "model" должен точно совпадать с одним из переданных ID (регистр можно игнорировать).
2) "tool" должен быть только из разрешённых значений выше.
3) "reason" должен быть коротким и конкретным.
4) Если есть сомнения, выбирай консервативный маршрут: tool="none" или "general".

Политика выбора инструмента:
- image_gen: явный запрос сгенерировать/нарисовать/создать изображение, иллюстрацию, арт.
- pdf_gen: явный запрос на готовый PDF, LaTeX, статью, презентацию/deck или юридический документ.
- deep_research: глубокий многоисточниковый анализ, отчёт, сравнение подходов, длинное исследование.
- web_search: нужны актуальные/живые факты (новости, цены, релизы, погода, "сегодня", "сейчас").
- audio_transcribe: пользователь прислал аудио/голос и просит распознать речь (STT, транскрипт).
- general: специализированный запрос без отдельного инструмента, но с обычным рассуждением ассистента.
- none: по умолчанию, когда отдельный инструментальный маршрут не требуется.

Политика выбора модели:
- Для image-ввода: предпочитай vision/мультимодальные модели.
- Для audio-ввода: предпочитай ASR/аудио-совместимые модели.
- Для задач с кодом: предпочитай coder/code модели.
- Для сложного анализа: предпочитай более мощные/крупные модели.
- Для коротких и простых задач: предпочитай быстрые/лёгкие модели.
- Фолбэк: наиболее сильная универсальная текстовая модель.
"""

_ROUTER_USER_TMPL = """\
Модальности: {modalities}
Модели: {models}

Сообщение: {message}"""


def _normalize_models(models: list[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in models or []:
        model_id = str(item or "").strip()
        if not model_id:
            continue
        if not _is_chat_capable_model(model_id):
            continue
        key = model_id.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(model_id)
    return ordered


def _pick_first(models: list[str], pattern: re.Pattern[str]) -> str | None:
    for model in models:
        if pattern.search(model):
            return model
    return None


# Известно-надёжные модели по тирам — приоритет над regex-подбором (иначе
# агрегаторы на 300+ моделей отдают алфавитно-первую «mini», часто битую/BYOK).
_PREFERRED_SMALL = ("openai/gpt-4o-mini", "gpt-4o-mini", "deepseek/deepseek-chat")
_PREFERRED_LARGE = (
    "openai/gpt-4o",
    "gpt-4o",
    "deepseek/deepseek-chat",
    "qwen/qwen-2.5-72b-instruct",
)

# Курируемый список надёжных чат-моделей. У агрегатора (RouterAI) 300+ моделей,
# многие — BYOK/битые/висящие (напр. arcee-ai/coder-large таймаутит). LLM-роутеру
# отдаём ТОЛЬКО этот шорт-лист (если он есть в каталоге), иначе он выбирает
# экзотику, которая падает по timeout. gpt-4o покрывает и код, и vision-вход.
_RELIABLE_CHAT_MODELS = (
    "openai/gpt-4o-mini",
    "gpt-4o-mini",
    "openai/gpt-4o",
    "gpt-4o",
    "openai/gpt-4o-2024-11-20",
    "deepseek/deepseek-chat",
    "deepseek-chat",
    "qwen/qwen-2.5-72b-instruct",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-flash-1.5",
    "mws-gpt-alpha",
)


def _pick_preferred(models: list[str], prefs: tuple[str, ...]) -> str | None:
    available = set(models)
    for pref in prefs:
        if pref in available:
            return pref
    return None


def _constrain_candidates(models: list[str]) -> list[str]:
    """Сузить кандидатов до курируемого шорт-листа надёжных моделей.

    Если ни одна надёжная модель недоступна у провайдера — возвращаем исходный
    список (лучше рискованный выбор, чем пустой). Порядок исходного списка
    сохраняем, чтобы не ломать модальные предпочтения regex-фолбэка.
    """
    allow = set(_RELIABLE_CHAT_MODELS)
    constrained = [m for m in models if m in allow]
    return constrained or models


async def _constrain_to_seeing(models: list[str]) -> list[str]:
    """Оставить только модели, которые ДЕЙСТВИТЕЛЬНО принимают изображение.

    🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. При `input_type="image"` кандидатами шли ВСЕ 411 моделей
    агрегатора («там своя семья моделей»), и роутер выбрал `aion-labs/aion-rp-llama-3.1-8b`
    — roleplay-модель на 8 миллиардов параметров — с обоснованием «Модель подходит для
    анализа изображений». Зрение в том прогоне отказало, в контексте лежала прямая
    заглушка «рассмотреть НЕ УДАЛОСЬ: не описывай и не угадывай», а ответ пришёл такой:

        Верх-лево: зеленовато-голубой; Верх-право: красновато-оранжевый; …

    На картинке были красный, зелёный, жёлтый и синий. Выдуманное описание своей картинки
    человек получает как факт — это хуже отказа.

    ⚠️ ПО КАТАЛОГУ, А НЕ ПО ИМЕНИ. Отбор по подстроке уже проверялся замером и провалился:
    10 незрячих среди совпавших и 160 зрячих мимо (см. `media._pick_vlm`, где живёт то же
    правило для выбора VLM). Каталог недоступен или зрячих нет — возвращаем исходный
    список: рискованный выбор лучше пустого.
    """
    try:
        from service.domain.client.registry import is_chat_capable
        from service.shared.model_catalog import get_openrouter_catalog, model_has_capability

        catalog = await get_openrouter_catalog()
        # 🔴 ЗРЕНИЕ И ЧАТ-ПРИГОДНОСТЬ — РАЗНЫЕ СВОЙСТВА, И ОДНОГО МАЛО. Замер после первой
        # редакции: отбор оставил `openai/gpt-5-image` (каталог честно помечает её зрячей),
        # роутер её выбрал, а чат-путь отверг — «Blocked non-chat model in chat path» — и
        # фейловер увёл на `aion-labs/aion-rp-llama-3.1-8b` без зрения. То есть правка
        # сработала и всё равно кончилась выдуманным описанием: генератор картинок ВИДИТ,
        # но отвечать словами не умеет.
        seeing = [
            m for m in models if model_has_capability(m, "vision", catalog) and is_chat_capable(m)
        ]
    except Exception:  # noqa: BLE001 — каталог необязателен, без него поведение прежнее
        logger.debug("model catalog unavailable", extra={"failure_code": "unavailable"})
        return models
    return seeing or models


def _pick_router_model(models: list[str]) -> str | None:
    preferred = _pick_preferred(models, _PREFERRED_SMALL)
    if preferred:
        return preferred
    fast = _pick_first(models, _FAST_MODEL_RE)
    if fast:
        return fast
    text = _pick_first(models, _TEXT_FAMILY_RE)
    if text:
        return text
    return models[0] if models else None


def _guard_tool_modality(tool: str, input_type: str | None) -> str:
    """Маршрут, требующий модальности, не срабатывает без неё.

    LLM-роутер иногда выдаёт `audio_transcribe` для текстовых и документных сообщений
    («вот файл» с .md), и инструмент уводил на ASR-агент — тот возвращал текст файла
    вместо анализа. Сбрасываем в обычную маршрутизацию (`tool="none"`).
    """
    return "none" if modality_conflict(tool, input_type) else tool


def _parse_llm_response(raw: str, available_models: list[str]) -> dict:
    cleaned = strip_json_fence(raw)
    data = json.loads(cleaned)

    model = data.get("model")
    if model and not any(m.lower() == model.lower() for m in available_models):
        model = None

    tool = canonical_route(str(data.get("tool", "none"))) or "none"
    if tool not in valid_router_tools():
        tool = "none"

    return {
        "model": model,
        "tool": tool,
        "reason": str(data.get("reason", "")),
    }


async def _llm_route(
    text: str,
    models: list[str],
    router_model: str,
    input_type: str | None,
    execution=None,
) -> dict | None:
    try:
        from service.domain.client import create_chat_completion
        from service.domain.model_runtime import invoke_model_call
        from service.domain.usage_ledger import UsageKind

        modalities = input_type if input_type and input_type != "text" else "text"
        if input_type and input_type != "text":
            modalities = f"text + {input_type}"

        result = await invoke_model_call(
            create_chat_completion,
            kind=UsageKind.ROUTE_MODEL,
            execution=execution,
            messages=[
                {"role": "system", "content": _ROUTER_SYSTEM},
                {
                    "role": "user",
                    "content": _ROUTER_USER_TMPL.format(
                        modalities=modalities,
                        models=", ".join(models) if models else "unknown",
                        message=text[:2000],
                    ),
                },
            ],
            model=router_model,
            temperature=0.0,
            max_tokens=150,
        )
        # Роутер — реальный провайдерский LLM-вызов на КАЖДОЕ авто-сообщение. Его usage
        # раньше выбрасывался → системный недобилл (аудит A2). Отдаём наверх для тарификации.
        response = result.response
        raw = first_message_content(response).strip()
        return _parse_llm_response(raw, models)
    except Exception:
        logger.debug("tool router unavailable", extra={"failure_code": "unavailable"})
        return None


def _detect_input_type(text: str, input_type: str | None) -> InputType:
    if isinstance(input_type, str):
        normalized = input_type.strip().lower()
        if normalized in {"text", "image", "audio", "video"}:
            return normalized  # type: ignore[return-value]

    low = (text or "").lower()
    if re.search(r"\.(png|jpg|jpeg|webp|gif|svg)\b|\bimage\b|\bphoto\b|изображ", low):
        return "image"
    if re.search(r"\.(mp3|wav|m4a|ogg|flac)\b|\baudio\b|\bspeech\b|\bvoice\b|аудио", low):
        return "audio"
    if re.search(r"\.(mp4|mov|avi|mkv|webm)\b|\bvideo\b|видео", low):
        return "video"
    return "text"


def _detect_text_kind(text: str) -> Literal["general", "code"]:
    low = (text or "").lower()
    if re.search(
        r"```|\bdef\b|\bclass\b|\bimport\b|\bfunction\b|\bconst\b|\bvar\b|\btraceback\b|\bstack trace\b",
        low,
    ):
        return "code"
    return "general"


def _detect_text_complexity(text: str) -> Literal["low", "medium", "high"]:
    value = text or ""
    low = value.lower()
    score = 0
    if len(value) > 300:
        score += 1
    if len(value) > 1200:
        score += 1
    if value.count("\n") >= 4:
        score += 1
    complexity_terms = re.findall(
        r"\b(если|когда|треб|огранич|сложн|оптим|архитект|edge case|performance|optimi[sz]e|constraint|pipeline)\w*\b",
        low,
    )
    if len(complexity_terms) >= 2:
        score += 1
    if score >= 2:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _regex_route(
    text: str,
    input_type: str | None,
    models: list[str],
) -> tuple[str | None, str, str | None, str | None, str]:
    routing_type = _detect_input_type(text, input_type)
    text_kind = None
    complexity = None
    resolved = None
    tool = "none"

    if routing_type == "image":
        resolved = _pick_first(models, _IMAGE_FAMILY_RE)
    elif routing_type == "audio":
        tool = "audio_transcribe"
        resolved = _pick_first(models, _TEXT_FAMILY_RE)
        routing_type = "text"
    elif routing_type == "video":
        resolved = _pick_first(models, _VIDEO_FAMILY_RE)

    if routing_type == "text":
        text_kind = _detect_text_kind(text)
        complexity = _detect_text_complexity(text)
        if text_kind == "code":
            resolved = _pick_preferred(models, _PREFERRED_LARGE) or _pick_first(
                models, _CODE_FAMILY_RE
            )
        if not resolved:
            if complexity == "high":
                resolved = _pick_preferred(models, _PREFERRED_LARGE) or _pick_first(
                    models, _LARGE_MODEL_RE
                )
            else:
                resolved = _pick_preferred(models, _PREFERRED_SMALL) or _pick_first(
                    models, _SMALL_MODEL_RE
                )
        if not resolved:
            resolved = _pick_preferred(models, _PREFERRED_SMALL) or _pick_first(
                models, _TEXT_FAMILY_RE
            )

    if not resolved and models:
        resolved = _pick_preferred(models, _PREFERRED_SMALL) or models[0]

    return resolved, routing_type, text_kind, complexity, tool


async def route_model(
    *,
    text: str,
    selected_model: str | None,
    input_type: str | None,
    available_models: list[str] | None = None,
    execution=None,
) -> tuple[str | None, dict]:
    """Resolve effective model and tool according to routing rules.

    Usage LLM-роутера записывается прямо в execution ledger. В ручном режиме
    роутер-LLM не вызывается и receipt не создаётся.
    """
    routed_input_type = _detect_input_type(text, input_type)
    models = _normalize_models(available_models)
    if not models:
        try:
            from service.domain.client import list_qualified_models
            from service.domain.client.model_requirements import ModelRequirement

            requirement = ModelRequirement(vision=routed_input_type == "image")
            models = _normalize_models(await list_qualified_models(requirement))
        except Exception:
            models = []

    meta: dict = {
        "requested_model": selected_model,
        "available_models_count": len(models),
    }

    manual_model = (selected_model or "").strip()
    if manual_model and manual_model.lower() != "auto":
        if not _is_chat_capable_model(manual_model):
            meta["manual_model_blocked"] = manual_model
        elif any(m.lower() == manual_model.lower() for m in models):
            explicit_tool = explicit_requested_tool(text)
            return manual_model, {
                **meta,
                "input_type": _detect_input_type(text, input_type),
                **({"tool": explicit_tool} if explicit_tool else {}),
                "source": "manual",
            }
        else:
            meta["manual_model_missing"] = manual_model
            raise SelectedModelUnavailable("selected model is unavailable")

    # Авто-режим: для ТЕКСТА сужаем кандидатов до курируемого шорт-листа надёжных
    # чат-моделей, иначе LLM-роутер выбирает экзотику из 300+ моделей агрегатора,
    # которая падает по timeout (напр. arcee-ai/coder-large). Для image/audio/video
    # оставляем полный список — там своя семья моделей (vision/ASR/gen), и шорт-лист
    # чат-моделей её бы отфильтровал.
    if routed_input_type == "text":
        candidates = _constrain_candidates(models)
    elif routed_input_type == "image":
        # Картинку обязана принимать сама модель ответа — иначе она рассуждает о том,
        # чего не видела, и делает это уверенно (замер — в `_constrain_to_seeing`).
        candidates = await _constrain_to_seeing(models)
    else:
        candidates = models
    meta["candidates_count"] = len(candidates)

    router_model = _pick_router_model(candidates)
    if router_model:
        llm_result = await _llm_route(
            text, candidates, router_model, input_type, execution=execution
        )
        if llm_result:
            resolved = llm_result["model"] or (candidates[0] if candidates else None)
            routed_tool = canonical_route(llm_result.get("tool")) or "none"
            return resolved, {
                **meta,
                "input_type": input_type or "text",
                "tool": _guard_tool_modality(routed_tool, routed_input_type),
                "reason": llm_result["reason"],
                "router_model": router_model,
                "source": "llm",
            }

    resolved, routing_type, text_kind, complexity, tool = _regex_route(text, input_type, candidates)
    return resolved, {
        **meta,
        "input_type": routing_type,
        "tool": _guard_tool_modality(tool, routed_input_type),
        "text_kind": text_kind,
        "complexity": complexity,
        "source": "regex_fallback",
    }
