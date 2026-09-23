"""Провайдерская медиа-аналитика: описание картинки (vision) и STT (Фаза 3).

Логика жила в backend-адаптере ``openai_media_analysis_adapter`` и напрямую импортила
``domain/client``. Это провайдерские вызовы: выбор VLM/аудио-модели, фейловер по здоровым
провайдерам, две STT-стратегии — всё поверх мультипровайдерного слоя, которым теперь
владеет сайдкар. Поэтому логика переехала в домен: сайдкар отдаёт её по HTTP, а backend
остаётся клиентом и сохраняет у себя ЛОКАЛЬНЫЙ whisper (он в домене не нуждается).

Две стратегии STT не случайны: у агрегаторов вроде OpenRouter НЕТ ``/audio/transcriptions``
(он только у нативного OpenAI), но аудио-вход через chat работает — поэтому сначала
аудио-чат, потом классический эндпоинт.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re

from .barcode import decode_barcodes, format_codes
from .client import list_qualified_models
from .client.model_requirements import ModelRequirement
from .client.protocol import ModelCallResult
from .model_runtime import invoke_model_call
from .run_context import RunExecutionContext, require_execution
from .usage_ledger import UsageKind

logger = logging.getLogger(__name__)

# Курируемый порядок предпочтения среди ЗРЯЧИХ моделей. Нужен потому, что зрение есть у
# 187 моделей из 468, и «первая по списку провайдера» — не выбор, а алфавит: на живом
# стенде так выбирался `baidu/ernie-4.5-vl-424b-a47b`, модель на 424 млрд параметров, для
# КАЖДОЙ картинки платформы. Отсутствующие имена просто пропускаются.
_PREFERRED_VLM: tuple[str, ...] = (
    "openai/gpt-4o-mini",
    "gpt-4o-mini",
    "openai/gpt-4o",
    "gpt-4o",
    "google/gemini-2.5-flash",
    "anthropic/claude-haiku-4.5",
    "qwen/qwen2.5-vl-72b-instruct",
)

# ⚠️ Фолбэк ПО ИМЕНИ остаётся, но применяется ТОЛЬКО к моделям, которых каталог не знает
# вовсе (нативные провайдеры и агрегаторы вне OpenRouter). Из него убраны `image` и
# `dall-e`: они ловят ГЕНЕРАТОРЫ картинок, а генератор, которого просят описать, отвечает
# картинкой или ошибкой — и то и другое приезжает пользователю как «описание».
_VLM_NAME_RE = re.compile(r"(vision|vl\b|vlm|multimodal|qwen.*vl|llava|pixtral)", re.I)


async def _pick_vlm(models: list[str], *, evidence_confirmed: bool = False) -> str | None:
    """Модель, которая ДЕЙСТВИТЕЛЬНО принимает изображение, или ``None``.

    🔴 По КАТАЛОГУ, а не по имени (обоснование и замер — в `model_has_capability`).
    Порядок: подтверждённые зрячие из курируемого списка → любая подтверждённая зрячая →
    только для НЕИЗВЕСТНЫХ каталогу моделей — совпадение по имени.
    """
    if evidence_confirmed:
        for preferred in _PREFERRED_VLM:
            if preferred in models:
                return preferred
        return models[0] if models else None

    from service.shared.model_catalog import (
        get_openrouter_catalog,
        model_has_capability,
        resolve_model_meta,
    )

    catalog = await get_openrouter_catalog()
    seeing = [m for m in models if model_has_capability(m, "vision", catalog)]
    for preferred in _PREFERRED_VLM:
        if preferred in seeing:
            return preferred
    if seeing:
        return seeing[0]
    unknown = (m for m in models if not resolve_model_meta(m, catalog))
    return next((m for m in unknown if _VLM_NAME_RE.search(m)), None)


def _pick_confirmed_vlm(models: list[str], _prefer: str | None = None) -> str | None:
    for preferred in _PREFERRED_VLM:
        if preferred in models:
            return preferred
    return models[0] if models else None


def _not_examined(filename: str, reason: str) -> str:
    """Текст для случая «посмотреть на пиксели НЕ УДАЛОСЬ» — прямым текстом.

    🔴 Прежняя заглушка «[Изображение загружено: file.png]» — ТОНКАЯ ПОДПИСЬ, и дальше по
    конвейеру никто уже не знает, что картинку не смотрели: модель получает имя файла и
    разворачивает его в правдоподобный текст. Живой замер: на `qr-code.gif` пришла
    энциклопедическая статья о том, что такое QR-код вообще — про содержимое ЭТОГО кода
    ни слова и ни одного признака, что прочитать не удалось.

    ⚠️ Тот же класс, что оговорки личностей и приписка об отклонённом режиме: текст,
    который обязан прозвучать, дописывается ДЕТЕРМИНИРОВАННО, а не выпрашивается промптом.
    """
    return (
        f"[Изображение «{filename}» получено, но рассмотреть его НЕ УДАЛОСЬ: {reason}. "
        "Не описывай и не угадывай, что на нём изображено, — скажи об этом пользователю.]"
    )


def _with_codes(codes: str, description: str) -> str:
    """Считанные коды идут ПЕРВЫМИ, описание — следом.

    Порядок несущий: содержимое кода — точные данные, описание — пересказ. Поставь
    пересказ выше, и модель ответит по нему («на изображении QR-код»), не дочитав до
    того единственного, о чём её спросили.
    """
    return f"{codes}\n\n{description}".strip() if codes else description


def frame_description(filename: str, description: str) -> str:
    """Обрамить ОПИСАНИЕ картинки так, чтобы его нельзя было принять за сами пиксели.

    🔴 Замер по коду: описание уезжало в промпт как обычный текст вложения — под общим
    заголовком «## Вложения текущей задачи», без единого слова о том, что это ПЕРЕСКАЗ
    пикселей, сделанный другой моделью. Отвечающая модель пикселей не видит вовсе
    (`ModalityAttachment.content` несёт текст), но по разметке этого не понять — и на
    «опиши подробно» она достраивала правдоподобные детали: книжные полки, мониторы и
    марку мебели, которых на фото не было.

    ⚠️ Тот же приём, что `_not_examined` и оговорки личностей: обязательное предложение
    дописывается ДЕТЕРМИНИРОВАННО. Просить об этом промптом уже пробовали — аналитику
    сказано «не домысливай», но его вывод пересказывает УЖЕ ДРУГАЯ модель, до которой
    та инструкция не доезжает.

    ⚠️ Пустое описание не обрамляем: рамка вокруг пустоты — та же тонкая подпись.
    """
    text = str(description or "").strip()
    # Уже обрамлено (`ОПИСАНИЕ`) или это отказ (`Изображение … НЕ УДАЛОСЬ`) — не трогаем:
    # повтор удвоил бы оговорку, а отказ превратил бы в «описание».
    if not text or text.startswith(("[ОПИСАНИЕ", "[Изображение")):
        return text
    return (
        f"[ОПИСАНИЕ изображения «{filename}», составленное моделью зрения. Самих пикселей "
        "у тебя нет — отвечай ТОЛЬКО по этому описанию. Чего в нём не названо, того на "
        "изображении ты не видел: не достраивай детали, а скажи, что их в описании нет.]\n"
        f"{text}"
    )


def audio_format(filename: str) -> str:
    low = str(filename or "").lower()
    for ext in ("wav", "mp3", "m4a", "ogg", "flac", "webm", "mp4"):
        if low.endswith(f".{ext}"):
            return "mp4" if ext == "m4a" else ext
    return "wav"


async def describe_image(
    content_bytes: bytes,
    content_type: str,
    filename: str,
    *,
    focus: str = "",
    execution: RunExecutionContext | None = None,
) -> str:
    """Описать картинку подходящей VLM.

    ``focus`` — УГОЛ ЗРЕНИЯ на самих пикселях (слот личности `vision`). Пусто → базовый
    промпт, байт-в-байт как раньше. Это второй слой специализации: аналитик решает, что
    вытянуть из ГОТОВОГО описания, а здесь решается, что вообще попадёт в описание.

    Execution context нужен для каждого фактического provider call: вызов настоящий и
    провайдеру; на аплоаде он один и учтён снаружи, но персонный пере-просмотр добавляет
    второй, и без учёта он был бы бесплатным для пользователя и платным для платформы —
    ровно тот класс дыр, что в проекте находили трижды (веер аналитиков, мета-вызовы,
    надбавка за непроизведённый артефакт).
    """
    # 🔴 КОДЫ ЧИТАЕМ ДЕТЕРМИНИРОВАННО И ДО ВСЕГО ОСТАЛЬНОГО. Декодер с коррекцией
    # Рида — Соломона либо прочитал, либо нет; VLM на том же кадре УГАДЫВАЕТ, и
    # угадывает правдоподобно (живой кадр: на `qr-code.gif` пришла статья про то, что
    # такое QR-код). Декодеру не нужны ни провайдер, ни модель со зрением — поэтому он
    # выше обеих проверок: код прочитается даже там, где смотреть было нечем.
    codes = format_codes(await asyncio.to_thread(decode_barcodes, content_bytes))

    active_execution = require_execution(execution)
    admission = active_execution.provider_admission
    image_data_url = (
        f"data:{content_type or 'image/png'};base64,{base64.b64encode(content_bytes).decode()}"
    )
    provider_name = None
    client = None
    if admission is not None:
        from .client.provider_operations import ProviderOperation

        decision = admission.admit_first(
            operation=ProviderOperation.VISION_INPUT,
            pick_model=_pick_confirmed_vlm,
        )
        vlm_model = decision.model if decision is not None else None
        provider_name = decision.provider if decision is not None else None
        client = decision.client if decision is not None else None
    else:
        vlm_model = await _pick_vlm(
            await list_qualified_models(ModelRequirement(vision=True)),
            evidence_confirmed=False,
        )
        if vlm_model is not None:
            from .client.provider_compat import resolve_model_client

            provider_name, client = await resolve_model_client(vlm_model)
    if vlm_model is None:
        return _with_codes(
            codes, _not_examined(filename, "среди доступных моделей нет ни одной со зрением")
        )
    if client is None:
        return _with_codes(codes, _not_examined(filename, "провайдер не настроен"))

    # 🔴 ОТКАЗ ПРОВАЙДЕРА НЕ УНОСИТ С СОБОЙ ПРОЧИТАННЫЙ КОД. Живой прогон на исчерпанном
    # ключе: декодер уже достал адрес из QR, а исключение из `create` вылетало наружу
    # целиком — сайдкар отвечал 500, и точные данные, полученные бесплатно и без модели,
    # выбрасывались. Зрение — лишь ОДИН из двух источников, и падение одного не отменяет
    # второго.
    #
    # ⚠️ Мой тест на «код читается без зрячей модели» этого не поймал: он мокал
    # «клиента нет», а не «клиент упал», — у зелёного была вторая причина.
    try:
        looked = await _look(
            client,
            vlm_model,
            image_data_url,
            focus,
            provider_name=provider_name,
            execution=active_execution,
        )
    except Exception as exc:  # noqa: BLE001 — чужой провайдер вправе отказать
        from service.domain.client.protocol import classify_provider_failure

        failure = classify_provider_failure(exc)
        logger.warning("vision integration failed code=%s", failure.code.value)
        return _with_codes(
            codes,
            _not_examined(filename, f"модель зрения недоступна ({failure.code.value})"),
        )
    if isinstance(looked, ModelCallResult):
        resp = looked.response
    else:  # compatibility for direct test adapters and historical monkeypatches
        resp = looked
        active_execution.usage.record_response(
            resp,
            provider=provider_name,
            model=vlm_model,
            kind=UsageKind.MULTIMODAL,
        )
    # Пустой ответ зрячей модели — тот же случай, что её отсутствие: смотреть было чем, но
    # описания нет. Молчаливая подпись здесь дала бы ровно ту же выдумку.
    described = getattr(resp.choices[0].message, "content", "")
    if not str(described or "").strip():
        return _with_codes(codes, _not_examined(filename, "модель не вернула описания"))
    # Обрамляем ЗДЕСЬ, у источника: описание расходится по двум путям (одиночное
    # вложение — прямо в промпт, несколько — через аналитика), и рамка в одном из них
    # означала бы, что второй по-прежнему выдаёт пересказ за наблюдение.
    return _with_codes(codes, frame_description(filename, described))


async def _look(
    client,
    vlm_model: str,
    image_data_url: str,
    focus: str,
    *,
    provider_name: str | None = None,
    execution: RunExecutionContext | None = None,
):
    """Один взгляд на пиксели. Вынесено, чтобы отказ провайдера ловился точечно."""
    return await invoke_model_call(
        client.chat.completions.create,
        model=vlm_model,
        kind=UsageKind.MULTIMODAL,
        provider_name=provider_name or "unknown",
        execution=execution,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {
                        "type": "text",
                        "text": (
                            # ⚠️ ОПИСАНИЕ ОБЯЗАНО БЫТЬ ПОЛНЫМ ПО СОСТАВУ, А НЕ ПО СТИЛЮ.
                            # Это ЕДИНСТВЕННЫЙ взгляд на пиксели: дальше по конвейеру
                            # работают только с этим текстом (`ModalityAttachment.content`
                            # несёт текст, не байты), и чего здесь нет — не восстановит
                            # уже никто. Прежняя формулировка просила «описать подробно»,
                            # и модель охотно давала прозу про настроение, но не число
                            # людей: на вопрос «сколько человек на фото» считать было
                            # НЕЧЕГО. Поэтому счёт объектов и дословный текст запрошены
                            # ЯВНО — они нужны любой специализации, а стиль пусть
                            # выбирает уже аналитик (слот `analyst.image`).
                            "Опиши, что изображено. Обязательно включи: "
                            "(1) СКОЛЬКО счётных объектов видно — людей, животных, "
                            "предметов, строк таблицы, элементов интерфейса — с точными "
                            "числами; если посчитать нельзя, скажи об этом прямо; "
                            "(2) ВЕСЬ читаемый текст, цифры, подписи, оси и легенды — "
                            "дословно; "
                            "(3) остальные важные детали: объекты, композицию, цвета, "
                            "символы, взаимное расположение." + (("\n\n" + focus) if focus else "")
                            # Угол зрения личности приписывается ПОСЛЕ базовых требований:
                            # он смещает акценты, но не отменяет счёт и дословный текст —
                            # они нужны и общему агенту, и следующим сообщениям.
                        ),
                    },
                ],
            }
        ],
        max_tokens=1000,
    )


async def transcribe_via_providers(
    content_bytes: bytes,
    filename: str,
    *,
    execution: RunExecutionContext | None = None,
) -> str:
    """STT по ЗДОРОВЫМ провайдерам с фейловером. → текст или '' (никто не смог).

    Раньше брался только АКТИВНЫЙ провайдер: мёртв или заблокирован — транскрипция
    падала целиком. Идём по failover-порядку, выкидывая выключенных админом и
    заблокированных health-проверкой (``drop_hard_off``), у каждого — его модели.
    """
    from .client.provider_compat import provider_client_models, provider_order
    from .client.provider_operations import ProviderOperation

    active_execution = require_execution(execution)
    admission = active_execution.provider_admission
    order = (
        list(admission.snapshot.provider_order) if admission is not None else await provider_order()
    )
    for pname in order:
        if admission is not None:
            decision = admission.admit(
                pname,
                operation=ProviderOperation.TRANSCRIPTION,
                pick_model=lambda models, _prefer: models[0] if models else None,
            )
            client = decision.client if decision.admitted else None
            available = [decision.model] if decision.admitted and decision.model else []
        else:
            client, available = await provider_client_models(pname)
        if client is None:
            continue
        text = await _transcribe_via_provider(
            client,
            available,
            content_bytes,
            filename,
            provider_name=pname,
            execution=execution,
        )
        if text:
            return text
    return ""


async def _transcribe_via_provider(
    client,
    available: list[str],
    content_bytes: bytes,
    filename: str,
    *,
    provider_name: str | None = None,
    execution: RunExecutionContext | None = None,
) -> str:
    """Две STT-стратегии у ОДНОГО провайдера: аудио-чат (gpt-audio/voxtral), затем
    /audio/transcriptions (нативный whisper). → распознанный текст или '' (провал)."""
    # 1) STT через chat/completions с аудио-моделями (gpt-audio / voxtral):
    #    у OpenRouter-подобных агрегаторов НЕТ эндпоинта /audio/transcriptions
    #    (он есть только у нативного OpenAI), но аудио-вход через chat работает.
    audio_models = [
        m
        for m in available
        if any(k in m.lower() for k in ("gpt-audio", "voxtral", "audio-preview"))
    ]
    # Порядок предпочтения: gpt-audio-mini → gpt-audio → voxtral/прочее.
    audio_models.sort(
        key=lambda m: 0 if "mini" in m.lower() else 1 if "gpt-audio" in m.lower() else 2
    )
    if audio_models:
        audio_b64 = base64.b64encode(content_bytes).decode()
        fmt = audio_format(filename)
        for model_id in audio_models[:3]:
            try:
                result = await invoke_model_call(
                    client.chat.completions.create,
                    model=model_id,
                    kind=UsageKind.AUDIO_TRANSCRIPTION,
                    provider_name=provider_name,
                    execution=execution,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": audio_b64,
                                        "format": fmt,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "Транскрибируй это аудио дословно. Верни ТОЛЬКО "
                                        "распознанный текст без комментариев и пояснений."
                                    ),
                                },
                            ],
                        }
                    ],
                    max_tokens=1500,
                )
                resp = result.response
                text = (getattr(resp.choices[0].message, "content", "") or "").strip()
                if text:
                    return text
            except Exception:
                continue

    # 2) Классический /audio/transcriptions — для нативного OpenAI / whisper-хостов.
    available_lower = {m.lower(): m for m in available}
    preferred = ["whisper-medium", "whisper-turbo-local", "whisper-large-v3", "whisper-1"]
    candidates: list[str] = []
    for name in preferred:
        actual = available_lower.get(name.lower())
        if actual and actual not in candidates:
            candidates.append(actual)
    for m in available:
        low = m.lower()
        if ("whisper" in low or "asr" in low or "stt" in low) and m not in candidates:
            candidates.append(m)

    for model_id in candidates:
        audio_file = io.BytesIO(content_bytes)
        audio_file.name = filename
        try:
            transcription = await client.audio.transcriptions.create(
                model=model_id, file=audio_file
            )
            if transcription.text:
                return transcription.text
        except Exception:
            continue
    return ""
