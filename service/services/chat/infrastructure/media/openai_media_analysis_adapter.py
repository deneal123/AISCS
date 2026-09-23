from __future__ import annotations

import base64
import logging

from service.infrastructure.sidecar import SidecarBadRequest, SidecarClient, SidecarError
from service.services.chat.application.ports.media_analysis_port import MediaAnalysisPort

logger = logging.getLogger(__name__)

# Медиа-байты едут base64 в JSON (+33% к размеру). Путь редкий — аплоад картинки/аудио, —
# поэтому отдельный multipart-транспорт ради него не городим; но таймаут щедрый: vision и
# STT это реальные LLM-вызовы.
_MEDIA_TIMEOUT_SEC = 180.0


def _client(config) -> SidecarClient:
    return SidecarClient(
        service="agents",
        base_url=str(getattr(config.agents, "sidecar_url", "") or ""),
        timeout=_MEDIA_TIMEOUT_SEC,
        api_key=str(getattr(config.agents, "llm_gateway_api_key", "") or ""),
    )


async def _sidecar_media(path: str, payload: dict, *, meta_out: dict | None = None) -> str | None:
    """Спросить медиа-ручку сайдкара. ``None`` = не смогли, отдай заглушку.

    Провайдерские vision/STT требуют мультипровайдерного слоя, которым владеет сайдкар.
    Локального пути больше нет: вызывающий переводит ``None`` в штатную заглушку
    («файл приложен, но не разобран»), а не роняет загрузку.

    ⚠️ Fail-open здесь ОСОЗНАННЫЙ, но теперь ЯВНЫЙ: раньше он был встроен в транспорт —
    любой исход, от «формат не поддержан» до «сервис лёг», сводился к одному `return
    None`, и по логу нельзя было понять, чинить у себя или ждать. Теперь «нас отвергли»
    (4xx) отличается от «сосед недоступен» (5xx/сеть) и пишется разными сообщениями.
    """
    from service.settings import config

    client = _client(config)
    try:
        data = await client.request_json("POST", path, json_body=payload)
    except SidecarBadRequest as exc:
        logger.info("agents sidecar: %s отверг запрос (%s): %s", path, exc.code, exc.detail)
        return None
    except SidecarError:
        logger.warning("agents sidecar: %s недоступен, отдаём заглушку", path, exc_info=True)
        return None
    # ⚠️ Ответ несёт не только текст: `usage` взгляда на пиксели нужен для тарификации, и
    # раньше он выбрасывался прямо здесь — вызов VLM оплачивала платформа.
    if meta_out is not None and isinstance(data, dict):
        meta_out.update(data)
    return str(data.get("text") or "")


class OpenAIMediaAnalysisAdapter(MediaAnalysisPort):
    # Метаданные последней транскрипции (для тарификации STT на аплоаде): движок,
    # модель, длительность. Заполняется для ОБОИХ движков — и локального whisper, и
    # провайдерского. Раньше провайдерский путь не заполнял это и считался бесплатным:
    # `resp.usage` в сайдкаре выбрасывался, эндпоинт отдавал только текст, а комментарий
    # уверял, что «тарифицируется токенами хода диалога» — но конвертация аудио→текст не
    # биллилась нигде, и юзер мог выбрать этот путь тумблером и транскрибировать даром.
    # Теперь оба движка тарифицируются по единой поминутной ставке (whisper_price_rub_per_min).
    last_transcription: dict | None = None

    # 🔴 USAGE ВЗГЛЯДА НА ПИКСЕЛИ. Описание картинки — ОТДЕЛЬНЫЙ платный вызов VLM на
    # загрузке, и его токены не попадают ни в один ход диалога. Пока ручка сайдкара
    # отдавала только текст, он не тарифицировался нигде: замерено 13 загруженных
    # картинок и НОЛЬ событий биллинга за них. Ставит метку только успешный взгляд —
    # отказ зрения услугой не является.
    last_image_usage: dict | None = None

    async def analyze_image(self, content_bytes: bytes, content_type: str, filename: str) -> str:
        # Сбрасываем ПЕРЕД попыткой: адаптер переиспользуется между загрузками, и чужой
        # usage ушёл бы в счёт следующего файла — та же причина, что у транскрипции.
        self.last_image_usage = None
        meta: dict = {}
        remote = await _sidecar_media(
            "/media/describe-image",
            {
                "content_b64": base64.b64encode(content_bytes).decode(),
                "content_type": content_type or "image/png",
                "filename": filename,
            },
            meta_out=meta,
        )
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else None
        # Метку ставит ТОЛЬКО состоявшийся взгляд: отказ зрения услугой не является, и
        # платить за него нельзя — то же правило, что для упавшего поиска.
        if remote and usage and int(usage.get("total") or 0) > 0:
            self.last_image_usage = dict(usage)
        # Не смогли — загрузку не роняем, это несоразмерно. Но заглушка ГОВОРИТ, что
        # картинку не смотрели.
        #
        # 🔴 Прежнее «[Изображение загружено: file.png]» — тонкая подпись, из которой
        # дальше по конвейеру не следует НИЧЕГО: модель видит имя файла и разворачивает
        # его в правдоподобный вымысел (живой замер: на `qr-code.gif` пришла статья о
        # том, что такое QR-код). Второй канал той же заглушки — у сайдкара
        # (`agents/service/domain/media.py:_not_examined`), и причина у каждого своя:
        # здесь «сосед не ответил», там «нет модели со зрением».
        #
        # ⚠️ Под этим `return` лежали 34 НЕДОСТИЖИМЫЕ строки — локальный VLM-путь,
        # оставшийся при переезде описания картинок в сайдкар. Он звал
        # `list_available_models` и `client`, которых в модуле уже нет: не «запасной
        # вариант», а гарантированный NameError, если бы до него дошли.
        return remote or (
            f"[Изображение «{filename}» получено, но рассмотреть его НЕ УДАЛОСЬ: "
            "сервис описания изображений не ответил. Не описывай и не угадывай, что на "
            "нём изображено, — скажи об этом пользователю.]"
        )

    @staticmethod
    def _audio_format(filename: str) -> str:
        low = str(filename or "").lower()
        for ext in ("wav", "mp3", "m4a", "ogg", "flac", "webm", "mp4"):
            if low.endswith(f".{ext}"):
                return "mp4" if ext == "m4a" else ext
        return "wav"

    async def transcribe_audio(
        self,
        content_bytes: bytes,
        filename: str,
        *,
        mode: str = "local",
        model: str | None = None,
        max_duration_sec: float | None = None,
    ) -> str:
        # Сбрасываем метку ПЕРЕД попыткой: инстанс адаптера может переиспользоваться между
        # загрузками, а тарифицируется тот, кто заполнит last_transcription. Без сброса
        # неаудийная загрузка вслед за аудио унесла бы в биллинг чужую длительность (дедуп
        # по хэшу файла её бы не поймал — хэш другой). Ставит метку только успешная ветка.
        self.last_transcription = None
        # 0) Локальный whisper.cpp (primary) — если включён и режим не «provider».
        if str(mode or "local").lower() != "provider":
            from service.services.chat.infrastructure.media.whisper_local_transcriber import (
                WhisperLocalTranscriber,
            )

            whisper = WhisperLocalTranscriber()
            if whisper.enabled:
                from service.settings import config as _cfg

                result = await whisper.transcribe(
                    content_bytes, model=model, max_duration_sec=max_duration_sec
                )
                text = str((result or {}).get("text") or "").strip()
                if text:
                    self.last_transcription = {
                        "engine": "local",
                        "model": str(
                            (result or {}).get("model")
                            or model
                            or _cfg.agents.whisper_default_model
                        ),
                        "duration_sec": float((result or {}).get("duration_sec") or 0.0),
                    }
                    return text
                # Локальный не смог → фолбэк на провайдера ниже (fail-open).

        # 🔴 ПРОВАЙДЕРСКИЙ ПУТЬ ЗАПИРАЕМ ОЦЕНКОЙ. У сайдкара провайдера нет точной
        # длительности до работы, а `mode=provider` выбирается тумблером — без этой
        # проверки обход был бы в один клик. Оценка для сжатых форматов занижена, поэтому
        # запор здесь мягче локального, но «час аудио на один кредит» он уже не пускает.
        if max_duration_sec is not None:
            from service.services.chat.infrastructure.media.whisper_local_transcriber import (
                TranscriptionTooExpensive,
                audio_duration_sec,
            )

            estimated, _ = audio_duration_sec(content_bytes)
            if estimated > float(max_duration_sec):
                raise TranscriptionTooExpensive(
                    f"запись длиной около {estimated:.0f} с дороже оплаченного "
                    f"(потолок {float(max_duration_sec):.0f} с)"
                )

        # Локальный не смог / mode=provider → ПРОВАЙДЕРСКИЙ STT: он требует
        # мультипровайдерного слоя, которым владеет сайдкар. Не ответил — отдаём ту же
        # честную заглушку, что и раньше, когда ни один провайдер не справился.
        remote = await _sidecar_media(
            "/media/transcribe",
            {
                "content_b64": base64.b64encode(content_bytes).decode(),
                "filename": filename,
            },
        )
        if remote:
            # Провайдерский STT — тоже платная транскрипция. Тарифицируем по той же
            # поминутной ставке, что и локальный whisper (единая цена независимо от
            # движка): считаем длительность из байтов (WAV точно, сжатые — оценкой) и
            # оставляем метку, которую снимет биллинг-блок аплоада.
            from service.services.chat.infrastructure.media.whisper_local_transcriber import (
                audio_duration_sec,
            )

            duration_sec, estimated = audio_duration_sec(content_bytes)
            self.last_transcription = {
                "engine": "provider",
                "model": str(model or ""),
                "duration_sec": duration_sec,
                "duration_estimated": estimated,
            }
            return remote
        return f"[Аудио файл: {filename}, транскрипция недоступна]"
