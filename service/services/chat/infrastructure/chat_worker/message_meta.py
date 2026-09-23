"""Метаданные хода: что показать пользователю и что оставить в БД.

Вынесено из `chat_worker_tasks.py` — файл давно за потолком храповика, а этот кусок
самодостаточен: чистые функции над словарями плюс один запрос к репозиторию. Смысловая
единица здесь одна — «что мы знаем про этот ход и в каком виде это переживает
перезагрузку».
"""

from __future__ import annotations

import logging
import re
from typing import Any

from service.infrastructure.agents_client.contracts.usage_kinds import SERVICE_USAGE_KINDS
from service.services.chat.domain.attachment_meta import user_message_meta
from service.services.chat.domain.mode_offer import sanitize_mode_offer_metadata
from service.services.chat.infrastructure.chat_worker.services import (
    ChatWorkerConversationService,
)
from service.services.chat.persistence.chat_worker_repository import ChatWorkerRepository

logger = logging.getLogger(__name__)

# ⚠️ `user_message_meta` ре-экспортируется: правило «что из вложения переживает F5»
# переехало в домен (писать реплику пользователя умеет не только воркер), а прежние
# импорты отсюда должны продолжать работать.
__all__ = [
    "build_public_usage_meta",
    "persistable_meta",
    "persona_switched",
    "reply_or_provider_failure",
    "user_message_meta",
]


def build_public_usage_meta(
    execution_result: dict,
    *,
    charged_credits: int,
    model: str | None,
    duration_ms: int | None = None,
    breakdown: dict | None = None,
) -> dict[str, Any] | None:
    """Безопасный whitelist per-message usage для клиента (токены/кредиты/модель/время).

    Сырой ``token_usage`` вырезается ReplyAssembler'ом как внутренние данные — наружу
    отдаём уже посчитанные агрегаты, чтобы UI показал «сколько стоило это сообщение».

    Время выполнения раньше не замерялось нигде: единственный `perf_counter` в проекте
    (chat_fallback_service) складывал результат в `_latency` и выбрасывал.
    """
    total = int(execution_result.get("total_tokens") or 0)
    # Время показываем даже когда токенов нет (кэш, ошибка провайдера) — вопрос
    # «сколько это заняло» законный сам по себе.
    if total <= 0 and not duration_ms:
        return None
    meta: dict[str, Any] = {
        "prompt": int(execution_result.get("prompt_tokens") or 0),
        "completion": int(execution_result.get("completion_tokens") or 0),
        "total": total,
        "model": model,
    }
    # Кто ОТВЕТИЛ на самом деле: при фейловере это может быть не выбранная человеком
    # модель. UI показывал только выбранную — человек видел «claude-haiku · 4505 кредитов»
    # при ответе от другой.
    #
    # 🔴 Служебные вызовы исключены: декомпозиция и сжатие ВСЕГДА идут на мета-модели, и
    # без фильтра бейдж горел на трёх ответах из четырёх.
    #
    # ⚠️ Вызов без `kind` считаем ОТВЕТОМ: так старый сайдкар шумит, но ничего не прячет.
    # Обратное умолчание скрывало бы настоящую подмену, а это денежный признак.
    actual = sorted(
        {
            str(call.get("model"))
            for call in (execution_result.get("per_call_usage") or [])
            if call.get("model")
            and str(call.get("model")) != str(model)
            and str(call.get("kind") or "") not in SERVICE_USAGE_KINDS
        }
    )
    if actual:
        meta["actual_model"] = actual[0] if len(actual) == 1 else ", ".join(actual)
    if charged_credits > 0:
        meta["credits"] = int(charged_credits)
    # Почему счёт больше, чем «столько-то токенов». Надбавка за инструмент — фиксированная
    # сумма за работу, а не за токены: у веб-поиска она перевешивала весь токенный счёт
    # (834 кредита против 733), и по паре чисел «2.9k т. · 1567 кр.» это выглядело как
    # непонятно дорогие токены. Кладём только когда надбавка была.
    surcharge = int((breakdown or {}).get("surcharge_credits") or 0)
    if surcharge > 0:
        meta["surcharge_credits"] = surcharge
        meta["surcharged_tools"] = [str(t) for t in (breakdown or {}).get("surcharged_tools") or []]
    if duration_ms and duration_ms > 0:
        meta["duration_ms"] = int(duration_ms)
    return meta


# Метаданные, которым есть смысл переживать перезагрузку. Сырой `b64_json` и служебную
# требуху в БД не пишем — только то, что рисует UI.
#
# ⚠️ `persona_ids` — единственный ключ здесь НЕ ради UI: без него запись о том, какая
# личность отвечала, не остаётся нигде (логи воркера режут результат по длине). По нему же
# `persona_switched` узнаёт, что роль сменилась посреди треда.
PERSISTED_META_KEYS = (
    "usage",
    "selected_model",
    "requested_authoring_model",
    "actual_authoring_model",
    "document_outcome",
    "document_failure_code",
    "document_project_saved",
    "execution_status",
    "generated_files",
    "model_routing",
    "sources",
    "pptx_b64",
    "persona_ids",
    # ⚠️ Без этого кольцо занятости ИСЧЕЗАЕТ после перезагрузки страницы: фронт ищет
    # последний отчёт в истории сообщений и, не найдя, показывает `hasWindow: false` до
    # следующего ответа. Человек видит пустое место там, где секунду назад был показатель.
    "context",
    # Предложение дорогого режима с кнопкой «запустить». Тот же класс дефекта, что выше:
    # без персиста кнопка исчезает после F5, и предложение, за которым стоит решение о
    # тысячах кредитов, теряется молча.
    "mode_offer",
)

_DOCUMENT_OUTCOMES = frozenset(
    {"awaiting_confirmation", "draft_ready", "completed", "deferred", "failed"}
)
_DOCUMENT_FAILURE_CODES = frozenset(
    {
        "draft_protocol",
        "draft_invalid",
        "evidence_incomplete",
        "source_conflict",
        "compile_failed",
        "deterministic_audit_failed",
        "visual_pending",
        "visual_audit_failed",
        "delivery_deferred",
        "selected_model_unavailable",
        "workspace_unavailable",
        "authoring_unsupported",
        "unresolved_requirements",
        "cancelled",
        "internal",
    }
)
_EXECUTION_STATUSES = frozenset({"completed", "partial", "deferred", "failed", "timed_out"})
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")


def persistable_meta(metadata: dict | None, file_url: str | None) -> dict:
    """Метаданные ассистентского сообщения для записи в БД.

    ⚠️ `file_url` — ПРЕСАЙН, он протухает. Кладём его для свежести, но настоящий якорь
    это `generated_files[].file_key`: по нему история перевыпустит ссылку заново. Иначе
    картинка отвалилась бы через несколько часов, и это выглядело бы как «опять пропала».
    """
    meta = sanitize_mode_offer_metadata(metadata)
    out = {k: meta[k] for k in PERSISTED_META_KEYS if meta.get(k) is not None}
    if out.get("document_outcome") not in _DOCUMENT_OUTCOMES:
        out.pop("document_outcome", None)
    if out.get("document_failure_code") not in _DOCUMENT_FAILURE_CODES:
        out.pop("document_failure_code", None)
    if out.get("execution_status") not in _EXECUTION_STATUSES:
        out.pop("execution_status", None)
    if out.get("document_project_saved") is not True:
        out.pop("document_project_saved", None)
    for key in ("requested_authoring_model", "actual_authoring_model"):
        value = str(out.get(key) or "")
        if not _SAFE_MODEL.fullmatch(value):
            out.pop(key, None)
    out.pop("pptx_b64", None)  # тяжёлый блоб в БД не нужен — файл уже в сторе
    if file_url:
        out["file_url"] = file_url
    return out


def reply_or_provider_failure(execution_result: dict) -> tuple[str, dict[str, Any]]:
    """Ответ хода. Пустой ответ модели превращаем в ЧЕСТНЫЙ ОТКАЗ, а не в молчание.

    🔴 Провал провайдера (403 «ключ исчерпан», недоступность, пустой стрим) доезжал
    сюда пустой строкой: воркер публиковал `agent_reply` без текста, фронт гасил
    спиннер и не показывал НИЧЕГО — ни ответа, ни ошибки. Снаружи это неотличимо от
    «запрос потерялся». HTTP-путь такую подмену делает давно
    (`chat_service.post_message`), воркер — нет, и разница была невидима: пути
    выглядят одинаково и оба заканчиваются `agent_reply`.
    """
    from service.services.chat.domain.chat_contracts import build_provider_unavailable_reply

    reply = str(execution_result["reply"])
    metadata: dict[str, Any] = dict(execution_result["metadata"] or {})
    if reply.strip():
        # Older sidecars only send the individual flags.  Normalize them at the
        # integration boundary so WS, Redis and persisted messages get the same
        # compact terminal state as newer agents.
        metadata.setdefault(
            "execution_status",
            "timed_out"
            if metadata.get("deadline_exceeded")
            else "partial"
            if metadata.get("partial_failure")
            else "completed",
        )
        return reply, metadata
    metadata["provider_unavailable"] = True
    metadata["execution_status"] = "failed"
    return build_provider_unavailable_reply(metadata.get("provider_error")), metadata


async def persona_switched(*, db_session, thread_id: str, persona_ids: list[str] | None) -> bool:
    """Сменилась ли роль по сравнению с прошлым ответом в этом треде.

    🔴 ЗАЧЕМ ЭТО ВООБЩЕ НУЖНО. Личность живёт в системной инструкции — одна строка. А в
    истории лежат предыдущие ходы, где ассистент УЖЕ показал другое поведение, и весят
    они кратно больше. Живой диалог это и показал: после переключения на «учёного» ответ
    остался в жанре предыдущей роли, хотя системная инструкция сменилась целиком.
    Инструкция не спорит с демонстрацией — нужен явный разрыв.

    Сравниваем МНОЖЕСТВА: порядок выбора меняет ведущую, но это перестановка, а не смена
    ролей — разрыв на неё только помешал бы держать единый стиль.

    Fail-open: не смогли прочитать — считаем, что смены не было. Лишний разрыв портит
    ответ заметнее, чем его отсутствие.
    """
    try:
        previous = await ChatWorkerConversationService(
            ChatWorkerRepository()
        ).last_assistant_persona_ids(db_session=db_session, thread_id=thread_id)
    except Exception:
        logger.debug(
            "не удалось прочитать личности прошлого ответа",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
        return False
    if previous is None:  # ответов ещё не было — сравнивать не с чем
        return False
    return set(previous) != {str(x) for x in (persona_ids or [])}
