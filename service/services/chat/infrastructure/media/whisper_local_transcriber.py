from __future__ import annotations

import io
import logging
import math
import wave

from service.infrastructure.sidecar import SidecarBadRequest, SidecarClient, SidecarError
from service.services.admin.application.runtime_settings import runtime_settings
from service.settings import config

logger = logging.getLogger(__name__)

# Оценка длительности сжатых форматов без аудио-библиотеки: ~128 кбит/с = 16000 байт/с.
# Грубо, но не даёт БЕСПЛАТНОЙ транскрипции на не-WAV (см. audio_duration_sec).
_ESTIMATE_BYTES_PER_SEC = 16000.0


def audio_duration_sec(content_bytes: bytes) -> tuple[float, bool]:
    """Длительность аудио в секундах для тарификации транскрипции: (секунды, оценка?).

    Нужна, чтобы ПРОВАЙДЕРСКИЙ STT тарифицировался по той же поминутной ставке, что и
    локальный whisper (единая цена транскрипции независимо от движка). У backend нет
    аудио-библиотеки, поэтому:
      • WAV читается ТОЧНО stdlib-модулем ``wave`` — голос с фронта конвертируется в
        WAV 16кГц (``voice.wav``), это основной тарифицируемый случай, ``estimated=False``;
      • сжатые форматы (mp3/ogg/m4a/webm — редкие загрузки файлом) точно не измерить,
        поэтому оцениваем по размеру при консервативном битрейте, ``estimated=True``.
        Списание НИКОГДА не обнуляется из-за формата (иначе не-WAV = бесплатный STT),
        флаг оценки уходит в метаданные списания.
    """
    if not content_bytes:
        return 0.0, False
    try:
        with wave.open(io.BytesIO(content_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 0
        if rate > 0 and frames > 0:
            return frames / float(rate), False
    except (wave.Error, EOFError, OSError):
        pass  # не WAV или битый заголовок — идём в оценку по размеру
    approx = len(content_bytes) / _ESTIMATE_BYTES_PER_SEC
    return (approx, True) if approx > 0 else (0.0, False)


def whisper_transcription_credits(duration_sec: float, model: str) -> tuple[int, float]:
    """Стоимость локальной транскрипции: (credits, raw_cost_rub).

    ₽ = (длительность_сек / 60) × ставка_₽_за_мин × множитель_тира_модели.
    credits = ceil(₽ / credit_unit_rub) — сходится с текущей кредитной экономикой
    (жирнее модель → больше множитель → дороже). Ставка и множители читаются через
    runtime-overlay (правятся в админке без передеплоя).
    """
    multipliers = (
        runtime_settings.get_agents(
            "whisper_model_multipliers", config.agents.whisper_model_multipliers
        )
        or {}
    )
    price_per_min = float(
        runtime_settings.get_agents(
            "whisper_price_rub_per_min", config.agents.whisper_price_rub_per_min
        )
    )
    mult = float(multipliers.get(model, 1.0))
    rub = (max(0.0, float(duration_sec)) / 60.0) * price_per_min * mult
    credit_unit = float(getattr(config.billing, "credit_unit_rub", 0.003) or 0.003)
    credits = max(1, math.ceil(rub / credit_unit)) if rub > 0 else 0
    return credits, rub


class TranscriptionTooExpensive(Exception):
    """Запись длиннее, чем покрывает остаток кредитов. Работа НЕ выполнена.

    🔴 ОТДЕЛЬНЫЙ КЛАСС, А НЕ ПУСТОЙ ОТВЕТ. Пустой ответ сайдкара означает «локальный не
    смог» и уводит в провайдерский фолбэк — то есть отказ по деньгам обернулся бы той же
    расшифровкой, только у провайдера и всё равно бесплатно. Отказ по цене обязан
    останавливать ВСЮ цепочку и доходить до человека словами.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def affordable_duration_sec(credits: int, model: str) -> float:
    """Сколько секунд расшифровки покрывает остаток кредитов. Обратная к цене.

    🔴 ЗАМЕРЕНО. Гейт загрузки спрашивал «есть ли кредиты», а не «хватает ли»: на счету
    ОДИН кредит, расшифровка восьми секунд (цена 3) выполнилась целиком, списался остаток —
    разницу заплатила платформа. Час аудио стоит 1000 кредитов, и пропускал его любой
    положительный баланс: одна загрузка — до тысячи кредитов даром, и повторять можно.

    ⚠️ Ноль кредитов — ноль секунд, а не «без ограничений». Отсутствие потолка выражается
    ОТСУТСТВИЕМ параметра у сайдкара; ноль обязан запрещать всё.
    """
    per_second, _ = whisper_transcription_credits(60.0, model)
    if per_second <= 0:
        return float("inf")  # цена не настроена — ограничивать нечем
    return max(0.0, float(credits)) * 60.0 / float(per_second)


class WhisperLocalTranscriber(SidecarClient):
    """HTTP-клиент к whisper.cpp-сайдкару (локальная STT, выбор модели per-request).

    ⚠️ ЧТО ИЗМЕНИЛОСЬ ПРИ ПЕРЕХОДЕ НА ОБЩУЮ БАЗУ. `list_models` брал таймаут литералом
    10.0, а `transcribe` — из конфига: два разных источника в ОДНОМ классе, и первый
    менялся только правкой кода. Оба сбоя гасились в пустое значение, поэтому «моделей
    нет» и «сайдкар не отвечает» выглядели для вызывающего одинаково.

    Fail-open сохранён СНАРУЖИ, а не внутри клиента: голос — не критичный путь, лучше
    ответить без расшифровки, чем уронить сообщение. Но теперь это решение принимается
    здесь явно, а не прячется в транспорте.
    """

    def __init__(self) -> None:
        super().__init__(
            service="whisper",
            base_url=config.agents.whisper_url or "",
            timeout=float(config.agents.whisper_timeout_sec or 600.0),
        )
        self._lang = config.agents.whisper_language or "ru"

    @property
    def enabled(self) -> bool:
        return bool(
            runtime_settings.get_agents("whisper_enabled", config.agents.whisper_enabled)
            and self.available
        )

    async def list_models(self) -> list[str]:
        if not self.enabled:
            return []
        try:
            data = await self.request_json("GET", "/models")
        except SidecarError:
            logger.debug("whisper list_models failed", exc_info=True)
            return []
        return list(data.get("models") or [])

    async def transcribe(
        self,
        content_bytes: bytes,
        *,
        model: str | None = None,
        language: str | None = None,
        max_duration_sec: float | None = None,
    ) -> dict:
        """Транскрипция через сайдкар. → {'text', 'model', 'duration_sec'} или {}.

        ⚠️ ``max_duration_sec`` — ЗАПОР ПЕРЕД ДОРОГОЙ РАБОТОЙ, выведенный из остатка
        кредитов. Оценка длительности на этой стороне для сжатых форматов ЗАНИЖЕНА (мы
        считаем по размеру при консервативном битрейте), поэтому одного гейта здесь мало:
        точную длительность знает только сайдкар — после ffmpeg и до запуска whisper.
        """
        if not self.enabled or not content_bytes:
            return {}
        params = {
            "model": model
            or runtime_settings.get_agents(
                "whisper_default_model", config.agents.whisper_default_model
            ),
            "lang": language or self._lang,
        }
        if max_duration_sec is not None:
            params["max_duration_sec"] = float(max_duration_sec)
        try:
            return await self.request_json(
                "POST",
                "/transcribe",
                params=params,
                content=content_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
        except SidecarBadRequest as exc:
            # 🔴 ОТКАЗ ПО ЦЕНЕ — НЕ «СЕРВИС НЕ СМОГ». Пустой ответ увёл бы в провайдерский
            # фолбэк, и запись, за которую не хватает денег, расшифровалась бы там — всё
            # так же за счёт платформы. Останавливаем цепочку целиком.
            if exc.code == "duration_exceeded":
                raise TranscriptionTooExpensive(str(exc.detail or "")) from exc
            # 503 «веса ещё качаются» и 413 «файл велик» — разные поводы, и оба
            # исправимы вызывающим. До таксономии оба были неотличимы от «сервис лёг».
            logger.warning("whisper отклонил запрос (%s): %s", exc.code, exc.detail)
            return {}
        except SidecarError:
            logger.warning("whisper sidecar transcribe failed", exc_info=True)
            return {}
