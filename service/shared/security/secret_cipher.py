"""Симметричное шифрование секретов (Fernet) поверх ``AUTH__SECRET``.

Ключ Fernet выводится детерминированно из ``config.auth.secret`` (SHA-256 →
urlsafe-base64), поэтому шифртексты переживают рестарт без отдельного управления
ключами. Используется для хранения провайдерских API-ключей в БД (см.
``provider_secrets``): в открытом виде ключ в базу не пишется и наружу не отдаётся.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from service.settings import config

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    """Fernet на детерминированном ключе из AUTH__SECRET.

    SHA-256 даёт ровно 32 байта, urlsafe-base64 из них — валидный ключ Fernet.
    """
    digest = hashlib.sha256((config.auth.secret or "").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Зашифровать секрет → ascii-токен для хранения в БД."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str | None:
    """Расшифровать токен → секрет; None при повреждении/смене AUTH__SECRET."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:  # InvalidToken и пр. — секрет нечитаем, ведём себя как «нет»
        logger.warning("provider secret decrypt failed (bad token or rotated AUTH__SECRET)")
        return None
