from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from service.composition.state import (
    get_billing_service,
    get_chat_application_service,
    get_optional_redis_client,
)
from service.infrastructure.graphify import GraphifyClient
from service.models.auth_models import AuthProfile
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.billing.application.billing_service import BillingService
from service.services.chat.application.use_cases.upload_file_use_case import (
    AttachmentIntentConflict,
    AttachmentPersistenceError,
    UploadFileUseCase,
)
from service.services.chat.infrastructure.media.openai_media_analysis_adapter import (
    OpenAIMediaAnalysisAdapter,
)
from service.services.chat.infrastructure.media.opendataloader_parser import OpenDataLoaderParser
from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    TranscriptionTooExpensive,
    whisper_transcription_credits,
)
from service.services.chat.presentation.routers.chat_api.schemas import UploadFileResponse
from service.shared.security.auth_checker import check_auth

logger = logging.getLogger(__name__)
upload_router = APIRouter()


# Окно дедупа списания транскрибации. Гасит быстрые дабл-сабмиты/ретраи одной загрузки
# (двойное списание за один файл), не трогая легитимную пере-транскрибацию позже.
_TRANSCRIPTION_DEDUP_TTL = 120


# Сколько граф репозитория «живёт» привязанным к треду. Как у thread-файла (2 ч):
# follow-up-вопросы по коду в пределах диалога должны находить репозиторий.
#
# ⚠️ НЕ ДОЛЬШЕ ПЕСОЧНИЦЫ. Архив разворачивается в её дерево, и карта описывает именно то,
# что там лежит: пережив песочницу, она стала бы картой каталога, которого уже нет, —
# агент искал бы по ней файлы и не находил. Берём МЕНЬШЕЕ из двух сроков.
def _repo_graphs_ttl_sec() -> int:
    from service.settings import config as cfg

    return min(7200, int(getattr(cfg.agents, "workspace_ttl_sec", 0) or 7200))


# Сколько ПОСЛЕДНИХ репозиториев треда держим для search_knowledge_graph. Больше — это и
# устаревшие версии в поиске, и graphify-запрос на каждый из них при каждом вызове.
_MAX_REPO_GRAPHS = 3


def _transcription_marker_key(user_id: str, content_hash: str) -> str:
    return f"transcription:charged:{user_id}:{content_hash}"


async def _claim_transcription_charge(redis_client: Any, user_id: str, content_hash: str) -> bool:
    """Атомарно «занять» право списать за эту транскрибацию. True → мы первые (списываем).

    `SET NX EX`: если маркер уже есть — это недавний дубль (второй сабмит/ретрай), возвращаем
    False и списание пропускаем. Fail-open: при сбое/отсутствии Redis возвращаем True —
    сбой дедупа не должен приводить к ПРОПУСКУ легитимного списания.
    """
    if redis_client is None:
        return True
    try:
        key = _transcription_marker_key(user_id, content_hash)
        was_set = await redis_client.set(key, "1", nx=True, ex=_TRANSCRIPTION_DEDUP_TTL)
        return bool(was_set)
    except Exception:
        logger.debug("transcription dedup claim failed; charging", exc_info=True)
        return True


async def _release_transcription_charge(redis_client: Any, user_id: str, content_hash: str) -> None:
    """Снять маркер, если списание НЕ удалось — чтобы ретрай в пределах окна мог списать."""
    if redis_client is None:
        return
    try:
        await redis_client.delete(_transcription_marker_key(user_id, content_hash))
    except Exception:
        logger.debug("transcription dedup release failed", exc_info=True)


async def _charge_image_usage(
    billing_service: BillingService,
    redis_client: Any,
    user_id: str,
    content_hash: str,
    usage: Any,
) -> None:
    """Списать за взгляд VLM на картинку по её РЕАЛЬНЫМ токенам.

    ⚠️ Цена берётся из общей таблицы моделей, а не выдумывается отдельной ставкой:
    зрячие модели различаются в цене на порядки, и фиксированная плата означала бы либо
    подарок на дорогой, либо грабёж на дешёвой.

    Дедуп по хэшу файла — как у транскрипции: дабл-сабмит и ретрай той же загрузки не
    должны стоить дважды. Best-effort: сбой списания не роняет загрузку.
    """
    if not isinstance(usage, dict):
        return
    total = int(usage.get("total") or 0)
    if total <= 0 or not user_id:
        return
    claimed = await _claim_transcription_charge(redis_client, user_id, f"img:{content_hash}")
    if not claimed:
        logger.info("image describe charge deduped (recent duplicate) user=%s", user_id)
        return
    try:
        from service.services.chat.infrastructure.chat_worker.charging import _charge_usage
        from service.services.chat.infrastructure.chat_worker.factory import (
            ChatWorkerDependencyFactory,
        )
        from service.settings import config as _cfg

        model = str(usage.get("model") or "")
        prompt = int(usage.get("prompt") or 0)
        completion = int(usage.get("completion") or 0)
        await _charge_usage(
            pg_connector=ChatWorkerDependencyFactory().create_pg_connector(_cfg),
            redis_client=redis_client,
            user_id=user_id,
            execution_result={
                "total_tokens": total,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "per_call_usage": [{"model": model, "prompt": prompt, "completion": completion}],
            },
            thread_id="",
            job_id=f"upload:{content_hash}:image",
            resolved_model=model or None,
            config=_cfg,
            reservation_id=None,
            reserved_estimate=0,
        )
    except Exception:
        # Маркер дедупа снимаем: иначе повтор загрузки останется бесплатным навсегда.
        await _release_transcription_charge(redis_client, user_id, f"img:{content_hash}")
        logger.warning("image describe charge failed", exc_info=True)


async def _affordable_transcription_sec(
    billing_service: BillingService, user_id: str, model: str | None
) -> float:
    """Сколько секунд расшифровки покрывает остаток человека. Fail-open по ДОСТУПНОСТИ.

    ⚠️ Сбой самого биллинга не должен запрещать загрузку (тот же принцип, что у гейта
    выше): не смогли спросить остаток — не ограничиваем. Ноль кредитов даёт ноль секунд,
    и это ЗАПРЕТ, а не «без ограничений».
    """
    from service.services.chat.infrastructure.media.whisper_local_transcriber import (
        affordable_duration_sec,
    )
    from service.settings import config as _cfg

    try:
        balance = await billing_service.get_balance(user_id)
    except Exception:
        logger.debug("не удалось узнать остаток для потолка расшифровки", exc_info=True)
        return float("inf")
    return affordable_duration_sec(
        int(balance.total or 0), str(model or _cfg.agents.whisper_default_model)
    )


async def _charge_transcription(
    billing_service: BillingService,
    redis_client: Any,
    user_id: str,
    content_hash: str,
    transcription: Any,
) -> None:
    """Списать за транскрипцию ОБОИХ движков (local и provider) по единой поминутной ставке.

    Провайдерский STT раньше был бесплатным: гейт стоял на ``engine=="local"``, а сайдкар
    выбрасывал usage — юзер мог выбрать провайдера тумблером и транскрибировать даром.
    Теперь адаптер заполняет ``last_transcription`` и для провайдера, а здесь тарифицируются
    оба. Best-effort: любая ошибка гасится, чтобы не ронять загрузку. Дедуп по хэшу файла
    защищает от двойного списания на дабл-сабмите/ретрае.
    """
    if not (
        isinstance(transcription, dict) and transcription.get("engine") in ("local", "provider")
    ):
        return
    engine = str(transcription.get("engine") or "")
    duration = float(transcription.get("duration_sec") or 0.0)
    model = str(transcription.get("model") or "")
    if duration <= 0:
        return
    credits, rub = whisper_transcription_credits(duration, model)
    if credits <= 0:
        return
    # Атомарно занимаем маркер по хэшу файла: дабл-сабмит/ретрай той же загрузки → маркер
    # занят → пропускаем (иначе двойное списание за одну загрузку).
    claimed = await _claim_transcription_charge(redis_client, user_id, content_hash)
    if not claimed:
        logger.info("%s transcription charge deduped (recent duplicate) user=%s", engine, user_id)
        return
    try:
        await billing_service.charge(
            user_id,
            credits=credits,
            tokens=0,
            raw_cost_rub=rub,
            metadata={
                "kind": "transcription",
                "engine": engine,
                "model": model,
                "duration_sec": round(duration, 2),
                "duration_estimated": bool(transcription.get("duration_estimated")),
            },
        )
    except Exception:
        # Списание не удалось — снимаем маркер, чтобы ретрай мог списать.
        await _release_transcription_charge(redis_client, user_id, content_hash)
        logger.warning("%s transcription charge failed", engine, exc_info=True)


def get_upload_use_case(file_service) -> UploadFileUseCase:
    return UploadFileUseCase(
        media_analysis_port=OpenAIMediaAnalysisAdapter(),
        file_service=file_service,
        document_parsing_port=OpenDataLoaderParser(),
        graph_client=GraphifyClient(),
    )


@upload_router.post("/upload", response_model=UploadFileResponse)
async def upload_file_to_chat(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    file: UploadFile = File(...),  # noqa: B008
    thread_id: str = Form(""),
    transcription_mode: str = Form("local"),
    transcription_model: str = Form(""),
    chat_application_service=Depends(get_chat_application_service),  # noqa: B008
    billing_service: BillingService = Depends(get_billing_service),  # noqa: B008
    redis_client=Depends(get_optional_redis_client),  # noqa: B008
    upload_intent_id: UUID | None = Form(None),  # noqa: B008
) -> UploadFileResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Кредитный гейт ДО дорогой обработки (транскрипция/медиа-анализ): списание идёт
    # пост-фактум и зажато GREATEST(0, ...), поэтому нулевой баланс иначе получал бы
    # платную операцию (сайдкар/LLM) бесплатно — работа уже сделана к моменту charge.
    # Fail-open по ДОСТУПНОСТИ: сбой самого биллинг-чека не должен ронять загрузку.
    try:
        has_credits = await billing_service.has_sufficient_credits(str(profile.user_id))
    except Exception:
        logger.debug("credit precheck failed on upload; allowing (fail-open)", exc_info=True)
        has_credits = True
    if not has_credits:
        raise HTTPException(
            status_code=402,
            detail="Недостаточно кредитов. Пополните баланс, чтобы обрабатывать вложения.",
        )

    content_bytes = await file.read()
    # Хэш содержимого — ключ дедупа списания транскрибации (см. ниже).
    content_hash = hashlib.sha256(content_bytes).hexdigest()[:32]
    # 🔴 ГЕЙТ ВЫШЕ ПРОВЕРЯЛ НАЛИЧИЕ ДЕНЕГ, А НЕ ДОСТАТОЧНОСТЬ. Замерено: на счету ОДИН
    # кредит, расшифровка восьми секунд (цена 3) выполнена целиком, списан остаток —
    # разницу заплатила платформа. Час аудио стоит 1000 кредитов, а пропускал его любой
    # положительный баланс. Переводим остаток в СЕКУНДЫ расшифровки и отдаём потолком.
    max_transcription_sec = await _affordable_transcription_sec(
        billing_service, str(profile.user_id), transcription_model
    )
    try:
        result = await get_upload_use_case(chat_application_service.file_service).execute(
            filename=file.filename,
            content_type=file.content_type,
            content_bytes=content_bytes,
            thread_id=thread_id,
            user_id=str(profile.user_id),
            transcription_mode=transcription_mode or "local",
            transcription_model=transcription_model or None,
            max_transcription_sec=max_transcription_sec,
            upload_intent_id=str(upload_intent_id) if upload_intent_id else None,
        )
    except AttachmentIntentConflict as exc:
        raise HTTPException(status_code=409, detail="upload_intent_conflict") from exc
    except AttachmentPersistenceError as exc:
        raise HTTPException(
            status_code=503,
            detail="Не удалось сохранить файл. Повторите загрузку.",
        ) from exc
    except TranscriptionTooExpensive as exc:
        # 🔴 402, А НЕ ТИХАЯ ПУСТОТА. Человек должен понять, что делать: запись длиннее,
        # чем покрывает остаток. Молчаливый пустой текст читался бы как «файл не понят».
        raise HTTPException(
            status_code=402,
            detail=f"Не хватает кредитов на расшифровку: {exc.detail}. Пополните баланс.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="File processing failed") from exc

    try:
        from service.services.chat.infrastructure.chat_worker.attachment_evidence import (
            cache_owner_attachment_evidence,
        )

        await cache_owner_attachment_evidence(
            redis_client,
            user_id=str(profile.user_id),
            upload_result=result,
        )
    except Exception:
        logger.debug(
            "attachment evidence cache unavailable",
            extra={"component": "chat_upload", "failure_code": "cache_unavailable"},
        )

    # Тарификация транскрипции (по длительности × тир модели), ОБА движка — локальный
    # whisper и провайдерский STT — по единой поминутной ставке. Best-effort: ошибка
    # списания не должна ронять загрузку. Раньше гейт был только на engine=="local", а
    # провайдерский путь считался бесплатным (юзер выбирал его тумблером и транскрибировал
    # даром); теперь адаптер заполняет метку и для провайдера.
    # Репозиторий разобран в граф repo-{uuid} — привязываем его к треду, чтобы инструмент
    # search_knowledge_graph искал КОД репо, а не только личные документы юзера (вариант B).
    # Живой инцидент: агент вызвал инструмент 9 раз, но искал в user-графе (PDF), кода репо
    # не нашёл — 9880 кредитов впустую. Best-effort: сбой Redis не должен ронять загрузку.
    repo_graph_id = result.pop("repo_graph_id", None)
    if repo_graph_id and thread_id and redis_client is not None:
        try:
            # ⚠️ СПИСОК с trim, а НЕ set. Каждая загрузка репо даёт НОВЫЙ graph_id (uuid), а
            # set копил бы их без предела: перезагрузил тот же репо после правки — старый
            # граф остаётся, и search_knowledge_graph видел бы УСТАРЕВШИЙ код; десять репо
            # в треде = десять graphify-запросов на каждый вызов инструмента. Держим
            # только N ПОСЛЕДНИХ (свежий репо вытесняет старый), новейший — первым.
            key = f"chat:{thread_id}:repo_graphs"
            await redis_client.lpush(key, repo_graph_id)
            await redis_client.ltrim(key, 0, _MAX_REPO_GRAPHS - 1)
            await redis_client.expire(key, _repo_graphs_ttl_sec())
        except Exception:
            logger.debug("не удалось привязать граф репозитория к треду", exc_info=True)

    transcription = result.pop("transcription", None)
    await _charge_transcription(
        billing_service, redis_client, str(profile.user_id), content_hash, transcription
    )
    # 🔴 ВЗГЛЯД НА ПИКСЕЛИ ТОЖЕ ПЛАТНЫЙ. Описание картинки — отдельный вызов VLM на
    # загрузке; его токены не попадают ни в один ход диалога, а ручка сайдкара прежде
    # отдавала один текст, выбрасывая usage. Замерено: 13 загруженных картинок и НОЛЬ
    # событий биллинга за них — платила платформа. Та же дыра уже была у провайдерского
    # STT, и лечится тем же способом.
    await _charge_image_usage(
        billing_service,
        redis_client,
        str(profile.user_id),
        content_hash,
        result.pop("image_usage", None),
    )

    _schedule_graph_indexing(result, str(profile.user_id), billing_service)
    return UploadFileResponse(**result)


# Форматы, которые имеет смысл класть в граф знаний. Картинки/аудио — нет: их «текст»
# это описание модели, связей между сущностями там не найти. zip уже стал графом на
# аплоаде (карта репозитория), второй раз индексировать незачем.
_INDEXABLE_TYPES = {"pdf", "docx", "doc", "odt", "rtf", "xlsx", "pptx", "text", "csv", "json", "md"}


def _schedule_graph_indexing(result: dict, user_id: str, billing_service: BillingService) -> None:
    """Фоново доклеить документ в личный граф знаний пользователя.

    Загрузку не тормозим: пользователь ждёт ответ эндпоинта, а индексация — это
    семантический проход LLM на минуты.

    Тарифицируем ЯВНО: проход идёт через наш шлюз (`/v1`), а шлюз кредиты **не
    списывает** — там только auth. Без этого индексация молча тратила бы наши деньги.
    """
    from service.infrastructure.graphify import (
        GraphifyClient,
        text_to_targz,
        user_graph_id,
    )
    from service.settings import config as cfg

    if not runtime_settings.get_agents("graph_index_enabled", cfg.agents.graph_index_enabled):
        return
    text = str(result.get("extracted_text") or "").strip()
    graph_id = user_graph_id(user_id)
    if not text or not graph_id or result.get("file_type") not in _INDEXABLE_TYPES:
        return

    client = GraphifyClient()
    if not client.enabled:
        return
    filename = str(result.get("filename") or "doc")

    async def _index() -> None:
        # Векторные чанки и граф строятся ПАРАЛЛЕЛЬНО и независимо: они отвечают на
        # разные вопросы (дословный фрагмент против связи), и падение одного не должно
        # лишать пользователя другого.
        from service.infrastructure.agents_client import sidecar_vector

        built, chunks = await asyncio.gather(
            client.build(text_to_targz(filename, text), graph_id=graph_id, mode="docs", merge=True),
            sidecar_vector.index_document_best_effort(
                cfg, user_id=user_id, filename=filename, text=text
            ),
        )
        if chunks:
            logger.info("проиндексировано чанков для векторного поиска: %s", chunks)
        if not built:
            return
        rub = float(cfg.agents.graph_index_price_rub_per_doc or 0.0)
        credit_unit = float(getattr(cfg.billing, "credit_unit_rub", 0.003) or 0.003)
        credits = max(1, math.ceil(rub / credit_unit)) if rub > 0 else 0
        if credits <= 0:
            return
        try:
            await billing_service.charge(
                user_id,
                credits=credits,
                tokens=0,
                raw_cost_rub=rub,
                metadata={
                    "kind": "graph_index",
                    "filename": filename,
                    "nodes": built.get("nodes"),
                    "edges": built.get("edges"),
                },
            )
        except Exception:
            logger.warning("graph index charge failed", exc_info=True)

    async def _guarded() -> None:
        try:
            await _index()
        except Exception:
            logger.warning("graph indexing failed for %s", filename, exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_guarded())
    except RuntimeError:
        logger.debug("no running loop — graph indexing skipped")


@upload_router.get("/transcription/config")
async def transcription_config(
    profile: Annotated[AuthProfile, Depends(check_auth)],
) -> dict:
    """Доступность локальной STT + список локальных whisper-моделей (для пикера)."""
    from service.services.admin.application.runtime_settings import runtime_settings
    from service.services.chat.infrastructure.media.whisper_local_transcriber import (
        WhisperLocalTranscriber,
    )
    from service.settings import config as cfg

    whisper = WhisperLocalTranscriber()
    models = await whisper.list_models() if whisper.enabled else []
    return {
        "local_enabled": whisper.enabled,
        "default_model": runtime_settings.get_agents(
            "whisper_default_model", cfg.agents.whisper_default_model
        ),
        "models": models,
    }
