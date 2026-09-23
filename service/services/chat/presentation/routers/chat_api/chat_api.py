import logging
import mimetypes
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from service.composition.state import (
    get_app_container,
    get_chat_application_service,
    get_optional_redis_client,
)
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.infrastructure.feedback_store import (
    feedback_key,
    get_feedback_map,
    set_feedback,
)
from service.services.chat.infrastructure.trace_store import get_trace_map, set_trace
from service.services.chat.presentation.http.upload_api import upload_router
from service.services.chat.presentation.routers.chat_api.schemas import (
    FeedbackRequest,
    MessageRequest,
    MessageResponse,
    ModelsResponse,
    ThreadCreate,
    ThreadResponse,
    ThreadUpdate,
    TraceSaveRequest,
)
from service.services.chat.presentation.routers.chat_api.workspace_api import workspace_router
from service.shared.security.auth_checker import check_auth

logger = logging.getLogger(__name__)


chat_router = APIRouter(prefix="/api/chats")
chat_router.include_router(upload_router)
# ⚠️ ВЫШЕ маршрутов вида `/{thread_id}`: тот ловит любой одиночный сегмент, и ручки
# рабочего места ушли бы в обработчик тредов — как это уже случалось с `/personas`.
chat_router.include_router(workspace_router)


@chat_router.get("/files/download")
async def download_generated_file(
    file_key: Annotated[str, Query(..., description="Storage file key or legacy local path")],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    filename: Annotated[str | None, Query(description="Optional download filename")] = None,
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    download = await service.download_generated_file(file_key=file_key, filename=filename)
    if "redirect_url" in download:
        return RedirectResponse(url=download["redirect_url"], status_code=307)
    media_type = mimetypes.guess_type(download["filename"])[0] or "application/octet-stream"
    return Response(
        content=download["payload"],
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{download["filename"]}"'},
    )


@chat_router.post("/{thread_id}/message", response_model=MessageResponse)
async def post_message(
    thread_id: str,
    payload: Annotated[MessageRequest, ...],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
) -> MessageResponse:
    result = await service.post_message(
        thread_id=thread_id, payload=payload, requester_id=str(profile.user_id)
    )
    return MessageResponse(
        reply=result["reply"],
        thread_id=result["thread_id"],
        metadata=result["metadata"],
    )


@chat_router.post(
    "/",
    response_model=ThreadResponse,
    status_code=201,
)
async def create_thread(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    payload: Annotated[ThreadCreate, ...] = Body(...),  # noqa: B008
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
) -> ThreadResponse:
    res = await service.create_thread(requester_id=str(profile.user_id), title=payload.title)
    return ThreadResponse(
        thread_id=res["thread_id"],
        title=res["title"],
        created_at=res.get("created_at"),
    )


@chat_router.get("/models", response_model=ModelsResponse)
async def get_models(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
) -> ModelsResponse:
    models = await service.get_models()
    return ModelsResponse(models=models)


@chat_router.get("/models/catalog")
async def get_models_catalog(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    return {"models": await service.get_models_catalog()}


@chat_router.get("/personas")
async def get_personas(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    """Личности для селектора в композере. Пусто — селектор просто не показывается.

    ⚠️ Объявлена ВЫШЕ `/{thread_id}`: тот ловит любой одиночный сегмент, и объявленная
    после него ручка ушла бы в обработчик тредов (и вернула бы 404 «тред не найден»).
    """
    return {"personas": await service.get_personas()}


@chat_router.get("/{thread_id}")
async def get_thread_messages(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    page: int = 1,
    per_page: int = 50,
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    result = await service.get_thread_messages(
        thread_id=thread_id, page=page, per_page=per_page, requester_id=str(profile.user_id)
    )
    # Прикрепляем сохранённый фидбэк (👍/👎) к сообщениям по контент-ключу, чтобы
    # оценка восстанавливалась при перечитывании треда.
    fb_map = await get_feedback_map(redis, thread_id)
    if fb_map:
        for msg in result.get("messages", []):
            if str(msg.get("sender")) in ("agent", "assistant"):
                rating = fb_map.get(feedback_key(msg.get("content", "")))
                if rating:
                    msg["feedback"] = rating
    return result


@chat_router.post("/{thread_id}/feedback", status_code=204)
async def set_message_feedback(
    thread_id: str,
    payload: Annotated[FeedbackRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    request: Request,
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    await set_feedback(redis, thread_id, payload.content_key, payload.rating)
    try:
        connector = get_app_container(request).infra.pg_connector
        from service.services.chat.persistence import workflow_catalog

        async with connector.get_session_context() as session:
            await workflow_catalog.apply_feedback(
                session,
                thread_id=thread_id,
                content_key=payload.content_key,
                user_id=str(profile.user_id),
                rating=payload.rating,
            )
            await session.commit()
    except Exception:
        # Ordinary feedback is already durable in Redis. Catalog learning is best-effort;
        # never turn a valid 👍/👎 into a client-visible server error because it is down.
        logger.warning(
            "workflow catalog feedback was not persisted",
            extra={"component": "workflow_catalog", "failure_code": "persistence"},
        )
    return None


@chat_router.put("/{thread_id}/trace", status_code=204)
async def save_thread_trace(
    thread_id: str,
    payload: Annotated[TraceSaveRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    await set_trace(redis, thread_id, payload.content_key, payload.trace)
    return None


@chat_router.get("/{thread_id}/trace")
async def get_thread_trace(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    return {"traces": await get_trace_map(redis, thread_id)}


@chat_router.get("/")
async def list_threads(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    page: int = 1,
    per_page: int = 50,
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    return await service.list_threads(
        requester_id=str(profile.user_id), page=page, per_page=per_page
    )


@chat_router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    await service.delete_thread(thread_id, requester_id=str(profile.user_id))
    return None


@chat_router.patch("/{thread_id}", response_model=ThreadResponse)
async def rename_thread(
    thread_id: str,
    payload: Annotated[ThreadUpdate, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
) -> ThreadResponse:
    res = await service.rename_thread(
        thread_id, title=payload.title, requester_id=str(profile.user_id)
    )
    return ThreadResponse(thread_id=res["thread_id"], title=res["title"])


@chat_router.post("/web-search")
async def web_search_endpoint(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    q: str = "",
    num_results: int = 5,
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    return await service.run_web_search(query=q, num_results=num_results)


@chat_router.post("/parse-url")
async def parse_url_endpoint(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    url: str = "",
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    try:
        return await service.parse_url_content(url=url)
    except HTTPException as exc:
        if exc.status_code == 400:
            raise
        logger.warning(
            "URL parse request failed",
            extra={"component": "chat", "failure_code": "remote"},
        )
        raise HTTPException(status_code=502, detail="Unable to fetch or parse URL content") from exc
    except Exception as exc:
        logger.error(
            "unexpected parse-url failure",
            extra={"component": "chat", "failure_code": "remote"},
        )
        raise HTTPException(status_code=502, detail="Unable to fetch or parse URL content") from exc


@chat_router.post("/generate-pptx")
async def generate_pptx_endpoint(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    topic: str = "",
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    try:
        generated = await service.generate_topic_pptx(topic=topic)
        return Response(
            content=generated["payload"],
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f'attachment; filename="{generated["filename"]}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "PPTX generation failed",
            extra={"component": "chat", "failure_code": "generation"},
        )
        raise HTTPException(status_code=500, detail="PPTX generation failed") from exc
