"""`/media/*` — провайдерские vision и STT.

Здесь только то, что требует мультипровайдерного слоя. ЛОКАЛЬНЫЙ whisper остаётся на
стороне backend: он ходит в свой сайдкар и провайдеров не касается — тащить его сюда
значило бы гонять аудио лишний раз по сети.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from service.domain.run_context import PrivateRunResources, use_run_execution
from service.presentation.deps import internal_auth
from service.schemas.vector import MediaAudioRequest, MediaImageRequest

router = APIRouter(prefix="/media")


def _unavailable(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "media_unavailable", "detail": "unavailable"}
    )


@router.post("/describe-image")
async def describe_image(
    payload: MediaImageRequest, authorization: str | None = Header(default=None)
) -> dict:
    """Описать картинку подходящей VLM (провайдерский vision).

    Выбор модели и клиент — из мультипровайдерного слоя, которым владеет сайдкар.
    Байты приезжают base64 в теле: путь редкий (аплоад картинки), отдельный
    multipart-транспорт ради него городить незачем.
    """
    # ⚠️ Ключ проверяется ПЕРВЫМ. Раньше проверка стояла после загрузки движка (у
    # `/vector/*` — после проверки хранилища), и неавторизованный запрос успевал
    # узнать, поднят ли сервис: 503 и 401 различимы снаружи.
    internal_auth(authorization)
    try:
        from service.domain import media
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)
    # 🔴 USAGE ВОЗВРАЩАЕМ ВСЕГДА. Без него вызов VLM на загрузке был БЕСПЛАТНЫМ для
    # человека и платным для платформы: замерено 13 загруженных картинок и НОЛЬ событий
    # биллинга за них. Ровно та же дыра уже была у провайдерского STT — там ручка тоже
    # отдавала один текст, а `usage` выбрасывался.
    with use_run_execution(PrivateRunResources()) as execution:
        from service.domain.client.registry import initialize_run_provider_admission

        await initialize_run_provider_admission(execution)
        text = await media.describe_image(
            base64.b64decode(payload.content_b64),
            payload.content_type,
            payload.filename,
            execution=execution,
        )
        usage = execution.usage.as_token_usage()
    return {"text": text, "usage": usage}


@router.post("/transcribe")
async def transcribe(
    payload: MediaAudioRequest, authorization: str | None = Header(default=None)
) -> dict:
    """Провайдерский STT с фейловером по здоровым провайдерам."""
    internal_auth(authorization)
    try:
        from service.domain import media
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)
    with use_run_execution(PrivateRunResources()) as execution:
        from service.domain.client.registry import initialize_run_provider_admission

        await initialize_run_provider_admission(execution)
        text = await media.transcribe_via_providers(
            base64.b64decode(payload.content_b64),
            payload.filename,
            execution=execution,
        )
    return {"text": text}
