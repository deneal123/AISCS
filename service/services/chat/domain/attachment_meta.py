"""Что из вложения пользователя переживает перезагрузку страницы.

Правило доменное, а путей записи хода ЧЕТЫРЕ: успешный прогон воркера, короткое
замыкание по кредитам, аварийный персист частичного ответа и фолбэк без воркера. Пока
функция жила в инфраструктуре воркера, три из четырёх писали реплику пользователя с
пустой метой — вложение было видно до F5 (жило в стейте фронта) и исчезало после.
"""

from __future__ import annotations

import re
from uuid import UUID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _safe_file_id(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


def user_message_meta(attachments: list | None) -> dict:
    """Вложения пользователя для истории — имя и тип, без содержимого.

    Сам текст вложения уже разобран и уехал в контекст/граф; хранить его копию в каждом
    сообщении значит раздувать таблицу ради того, что и так есть.
    """
    items = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        name = str(att.get("name") or att.get("filename") or "").strip()
        if not name:
            continue
        file_id = _safe_file_id(att.get("file_id"))
        digest = str(att.get("digest") or att.get("sha256") or "").lower()
        mime_type = str(att.get("mime_type") or "")[:120]
        items.append(
            {
                "filename": name,
                "file_type": str(att.get("kind") or "document")[:32],
                **({"file_id": file_id} if file_id else {}),
                **({"mime_type": mime_type} if mime_type else {}),
                **({"digest": digest} if _SHA256.fullmatch(digest) else {}),
            }
        )
    return {"attachments": items} if items else {}
