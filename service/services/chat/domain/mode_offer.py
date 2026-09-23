"""Срок жизни предложения дорогого режима — по СЕРВЕРНЫМ часам.

🔴 Предложение висело под ответом вечно. Человек либо жал кнопку задним числом — через
час, когда ответ уже прочитан и не нужен, — либо оно просто мозолило глаза. Решение о
тысячах кредитов имеет смысл ПО ХОДУ работы, значит и жить оно должно ровно столько.

🔴 ОТСЧЁТ НЕ МОЖЕТ ЖИТЬ В БРАУЗЕРЕ. Таймер в интерфейсе переживают перезагрузкой, второй
вкладкой и сменой системного времени. Поэтому предложение несёт серверный `offered_at`,
а решение «просрочено» принимается здесь, на отдаче истории: клиент по этим полям только
РИСУЕТ остаток.

⚠️ Молчание = ОТКАЗ, и это единственный безопасный дефолт. Автозапуск по таймауту
означал бы списание тысяч кредитов у человека, который отошёл от экрана.

⚠️ Просроченное предложение НЕ УДАЛЯЕТСЯ из метаданных: исчезнувшая карточка
неотличима от «предложения не было». Оно остаётся СЛЕДОМ решения (`expired: true`), а
рычагом быть перестаёт.
"""

from __future__ import annotations

from datetime import UTC, datetime

# Если сайдкар прислал предложение без срока (старая запись в БД), считаем его
# просроченным: живой рычаг из данных, происхождение которых мы не знаем, опаснее
# потерянной кнопки — обычный путь запустить режим у человека остаётся.
DEFAULT_TTL_SEC = 30
_AUTO_REASON_CODES = frozenset(
    {
        "shortcut_empty",
        "shortcut_smalltalk",
        "shortcut_continue",
        "model_classification",
        "confirmation_required",
        "video_confirmation_required",
        "disabled",
        "explicit_route",
        "explicit_search",
        "nontext_input",
        "multimodal_input",
        "pre_resolved_route",
        "decision_unavailable",
    }
)


def _safe_reason_code(value: object) -> str | None:
    code = str(value or "")
    return code if code in _AUTO_REASON_CODES else None


def sanitize_mode_offer_metadata(meta: dict | None) -> dict:
    """Keep confirmation metadata opaque at every public/persisted boundary.

    The original request is already the user message anchoring the trace.  It
    must not be duplicated into an offer that is streamed, logged, or stored as
    assistant metadata.  The shallow copy deliberately preserves the bounded
    confirmation contract while redacting records emitted by older sidecars.
    """
    if not isinstance(meta, dict):
        return meta or {}
    sanitized = dict(meta)
    for key in ("auto", "mode_offer"):
        value = sanitized.get(key)
        if not isinstance(value, dict):
            continue
        cleaned = {
            item_key: item_value
            for item_key, item_value in value.items()
            if item_key not in {"prompt", "reason"}
        }
        reason_code = _safe_reason_code(value.get("reason_code"))
        if reason_code is None:
            cleaned.pop("reason_code", None)
        else:
            cleaned["reason_code"] = reason_code
        sanitized[key] = cleaned
    if sanitized.get("kind") == "legacy_route_used":
        sanitized.pop("reason", None)
        reason_code = _safe_reason_code(sanitized.get("reason_code"))
        if reason_code is None:
            sanitized.pop("reason_code", None)
        else:
            sanitized["reason_code"] = reason_code
    return sanitized


def expire_mode_offer(meta: dict | None, *, now: datetime | None = None) -> dict:
    """Пометить предложение просроченным, если его срок вышел. Иначе — вернуть как есть."""
    meta = sanitize_mode_offer_metadata(meta)
    offer = meta.get("mode_offer")
    if not isinstance(offer, dict) or not offer.get("mode"):
        return meta
    if offer.get("status") == "accepted":
        accepted = dict(offer)
        accepted.pop("expired", None)
        return {**meta, "mode_offer": accepted}
    if offer.get("expired"):
        return meta

    moment = now or datetime.now(UTC)
    offered_at = _parse_ts(offer.get("offered_at"))
    ttl = _positive_int(offer.get("expires_in_sec"), DEFAULT_TTL_SEC)
    if offered_at is not None and (moment - offered_at).total_seconds() < ttl:
        return meta
    return {**meta, "mode_offer": {**offer, "expired": True}}


def _parse_ts(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _positive_int(value, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback
