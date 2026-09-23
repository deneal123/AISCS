"""Расшифровка не делается в долг: потолок длительности выведен из остатка кредитов.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Пользователю оставлен ОДИН кредит, загружен wav на 8 секунд:

    загрузка: audio | извлечено символов: 26
    баланс: 1 → 0 (списано 1)

Расшифровка выполнена целиком. Её цена — 3 кредита (8 с по поминутной ставке), списан
остаток, разницу заплатила платформа. Гейт загрузки спрашивал «есть ли кредиты», а не
«хватает ли»: цена узнаётся только ПОСЛЕ работы, а `charge` обрезан `GREATEST(0, …)`.

Масштаб виден в самой цене: минута — 17 кредитов, час — 1000. Любой положительный баланс
пропускал часовую запись, и повторять это можно было сколько угодно.

Лечение — то же, что уже стоит в video-сайдкаре: потолок длительности, проверяемый ТАМ,
ГДЕ ДЛИТЕЛЬНОСТЬ ИЗВЕСТНА ДО ДОРОГОЙ ЧАСТИ. У whisper это точка сразу после ffmpeg и до
запуска whisper-cli. На стороне backend остаётся оценка — для сжатых форматов она
занижена, поэтому одного гейта здесь мало и он не единственный.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    TranscriptionTooExpensive,
    affordable_duration_sec,
    whisper_transcription_credits,
)

MODEL = "base"


def test_the_ceiling_matches_the_price():
    """🔴 ГЛАВНОЕ: потолок и цена — одна и та же шкала, иначе гейт либо душит платящих,
    либо снова раздаёт расшифровку даром."""
    for credits in (1, 17, 100, 1000):
        seconds = affordable_duration_sec(credits, MODEL)
        charged, _ = whisper_transcription_credits(seconds, MODEL)

        assert charged <= credits + 1, (
            f"{credits} кр. дают {seconds:.0f} с, а стоят они {charged} кр. — платит платформа"
        )


def test_the_measured_case_is_now_refused():
    """🔴 ИМЕННО ЗАМЕРЕННЫЙ СЛУЧАЙ: один кредит и запись на 8 секунд ценой 3."""
    assert whisper_transcription_credits(8.0, MODEL)[0] == 3, "цена замера изменилась"

    assert affordable_duration_sec(1, MODEL) < 8.0, "одного кредита снова хватает на 8 секунд"


def test_no_credits_means_no_seconds():
    """🔴 ГРАНИЦА, НА КОТОРОЙ УЖЕ СПОТЫКАЛИСЬ. Ноль кредитов — ноль секунд. Соблазн
    трактовать ноль как «без ограничений» стоил video-сайдкару сквозного прохода:
    `0 > 7200` ложно, и потолок пропускал всё."""
    assert affordable_duration_sec(0, MODEL) == 0.0


def test_an_unpriced_model_is_not_throttled():
    """⚠️ Цена не настроена (ставка 0) — ограничивать нечем, и выдумывать потолок нельзя:
    это запретило бы расшифровку всем."""
    import service.services.chat.infrastructure.media.whisper_local_transcriber as wlt

    original = wlt.whisper_transcription_credits
    wlt.whisper_transcription_credits = lambda *a, **k: (0, 0.0)
    try:
        assert wlt.affordable_duration_sec(5, MODEL) == float("inf")
    finally:
        wlt.whisper_transcription_credits = original


# --- отказ по цене останавливает ВСЮ цепочку --------------------------------------------- #


@pytest.mark.asyncio
async def test_a_price_refusal_does_not_fall_back_to_the_provider():
    """🔴 ДЫРА В САМОЙ ПРАВКЕ, найденная при её написании. Локальный сайдкар отказывает по
    цене → адаптер прежде читал это как «локальный не смог» и уходил в провайдерский STT:
    та же расшифровка, только у провайдера и всё так же за счёт платформы.
    """
    import service.services.chat.infrastructure.media.whisper_local_transcriber as wlt
    from service.services.chat.infrastructure.media.openai_media_analysis_adapter import (
        OpenAIMediaAnalysisAdapter,
    )

    class _Refusing(wlt.WhisperLocalTranscriber):
        def __init__(self):  # noqa: D107 — двойник, конфиг сайдкара не нужен
            pass

        @property
        def enabled(self):
            return True

        async def transcribe(self, *a, **kw):
            raise TranscriptionTooExpensive("запись длиной 3600 с дороже оплаченного")

    original = wlt.WhisperLocalTranscriber
    wlt.WhisperLocalTranscriber = _Refusing
    try:
        with pytest.raises(TranscriptionTooExpensive):
            await OpenAIMediaAnalysisAdapter().transcribe_audio(
                b"RIFF....", "voice.wav", max_duration_sec=1.0
            )
    finally:
        wlt.WhisperLocalTranscriber = original


@pytest.mark.asyncio
async def test_the_provider_path_is_gated_by_the_estimate():
    """🔴 ОБХОД В ОДИН КЛИК. `mode=provider` выбирается тумблером, а у провайдера точной
    длительности до работы нет. Без гейта по оценке правка чинила бы только локальный путь.
    """
    from service.services.chat.infrastructure.media.openai_media_analysis_adapter import (
        OpenAIMediaAnalysisAdapter,
    )

    # Мегабайт «аудио» — оценка около 65 секунд при потолке в одну.
    with pytest.raises(TranscriptionTooExpensive):
        await OpenAIMediaAnalysisAdapter().transcribe_audio(
            b"\x00" * 1_000_000, "voice.mp3", mode="provider", max_duration_sec=1.0
        )


@pytest.mark.asyncio
async def test_a_short_record_passes_the_provider_gate(monkeypatch):
    """🔴 ГРАНИЦА С ДРУГОЙ СТОРОНЫ: короткая запись при том же потолке обязана пройти,
    иначе гейт превращается в запрет расшифровки как таковой."""
    from service.services.chat.infrastructure.media import openai_media_analysis_adapter as ada

    async def _sidecar(path, payload):
        return {"text": "расшифровано"}

    monkeypatch.setattr(ada, "_sidecar_media", _sidecar)

    text = await ada.OpenAIMediaAnalysisAdapter().transcribe_audio(
        b"\x00" * 8_000, "voice.mp3", mode="provider", max_duration_sec=60.0
    )

    assert "расшифровано" in str(text)


# --- точки вызова ------------------------------------------------------------------------ #


def test_the_upload_endpoint_computes_the_ceiling():
    """🔴 ТОЧКА ВЫЗОВА. Правило верно, но если ручка не считает потолок — оно мертво, и
    расшифровка снова идёт в долг. Разбираем ДЕРЕВО: подстрока нашлась бы в комментарии."""
    import ast
    import inspect

    from service.services.chat.presentation.http import upload_api

    tree = ast.parse(inspect.getsource(upload_api.upload_file_to_chat).strip())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_affordable_transcription_sec"
    ]

    assert calls, "ручка не выводит потолок из остатка — расшифровка снова в долг"


def test_the_ceiling_reaches_the_sidecar():
    """🔴 ВТОРАЯ ТОЧКА ВЫЗОВА. Оценка на нашей стороне для сжатых форматов ЗАНИЖЕНА;
    точную длительность знает только сайдкар. Не доедет параметр — останется гейт, который
    легко обойти файлом плотнее ожидаемого."""
    import ast
    import inspect

    from service.services.chat.infrastructure.media import whisper_local_transcriber as wlt

    tree = ast.parse(inspect.getsource(wlt.WhisperLocalTranscriber.transcribe).strip())
    assigned = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(getattr(node, "slice", None), ast.Constant)
        and node.slice.value == "max_duration_sec"
    ]

    assert assigned, "потолок не кладётся в параметры запроса — сайдкар о нём не узнает"


@pytest.mark.asyncio
async def test_the_client_turns_a_402_into_a_price_refusal(monkeypatch):
    """🔴 СТРАЖ БЫЛ СЛЕП, И МУТАЦИЯ ЭТО ПОКАЗАЛА. Тест выше подменяет клиент целиком и сам
    бросает отказ — то есть проверяет адаптер, а не КЛИЕНТА. Убери разбор кода
    `duration_exceeded` в клиенте, и отказ по цене снова станет пустым ответом «локальный
    не смог» → провайдерский фолбэк → бесплатная расшифровка.
    """
    import service.services.chat.infrastructure.media.whisper_local_transcriber as wlt
    from service.infrastructure.sidecar import SidecarBadRequest

    client = wlt.WhisperLocalTranscriber()
    monkeypatch.setattr(type(client), "enabled", property(lambda self: True))

    async def _refuse(*a, **kw):
        raise SidecarBadRequest(
            "whisper", "duration_exceeded", "запись длиной 3600 с дороже оплаченного"
        )

    monkeypatch.setattr(client, "request_json", _refuse)

    with pytest.raises(TranscriptionTooExpensive):
        await client.transcribe(b"audio", max_duration_sec=60.0)


@pytest.mark.asyncio
async def test_other_sidecar_refusals_stay_soft(monkeypatch):
    """🔴 ГРАНИЦА. «Веса ещё качаются» и «файл велик» — не про деньги: там фолбэк на
    провайдера уместен, и превращать их в жёсткий отказ нельзя."""
    import service.services.chat.infrastructure.media.whisper_local_transcriber as wlt
    from service.infrastructure.sidecar import SidecarBadRequest

    client = wlt.WhisperLocalTranscriber()
    monkeypatch.setattr(type(client), "enabled", property(lambda self: True))

    async def _refuse(*a, **kw):
        raise SidecarBadRequest("whisper", "model_unavailable", "модель ещё не скачана")

    monkeypatch.setattr(client, "request_json", _refuse)

    assert await client.transcribe(b"audio", max_duration_sec=60.0) == {}
