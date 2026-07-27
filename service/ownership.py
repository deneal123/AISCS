"""Токен владения песочницей.

🔴 ЗАЧЕМ. Идентификатор песочницы ездит в теле `/run` и попадает в трейс, а значит его
можно увидеть и подставить. Без подписи угаданный или подсмотренный `workspace_id` — это
доступ к чужой файловой системе: сервис не знает, кто спрашивает, кроме как по этому полю.
Подписывает backend (у него есть личность пользователя), проверяет сайдкар.

⚠️ Сравнение ТОЛЬКО `compare_digest`: обычное `==` на строках выходит по первому
несовпавшему байту, и по времени ответа подпись подбирается побайтово.

⚠️ Секрет обязателен: без него сервис не стартует. Дефолтный ключ в такой роли — это
подпись, которую умеет ставить кто угодно, то есть отсутствие подписи с видом наличия.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

MIN_SECRET_LEN = 16
# Срок токена. Короткий: он выдаётся на создание песочницы, а живёт она минуты.
DEFAULT_TTL_SEC = 4 * 3600


class OwnershipError(Exception):
    """Токен не подошёл: подделан, просрочен или выдан на другую песочницу."""


def _secret() -> str:
    secret = str(os.environ.get("WORKSPACE_OWNER_SECRET", "") or "")
    if len(secret) < MIN_SECRET_LEN:
        raise RuntimeError(
            f"WORKSPACE_OWNER_SECRET не задан или короче {MIN_SECRET_LEN} символов — "
            "без него токен владения подделывается, и сервис работать не должен"
        )
    return secret


def _sign(workspace_id: str, user_id: str, expires_at: int) -> str:
    payload = f"{workspace_id}|{user_id}|{expires_at}".encode()
    return hmac.new(_secret().encode(), payload, hashlib.sha256).hexdigest()


def mint(workspace_id: str, user_id: str, ttl_sec: float = DEFAULT_TTL_SEC) -> str:
    """Выдать токен вида ``<exp>.<подпись>``."""
    expires_at = int(time.time() + max(1.0, ttl_sec))
    return f"{expires_at}.{_sign(workspace_id, user_id, expires_at)}"


def verify(token: str, workspace_id: str, user_id: str) -> None:
    """Проверить токен. Любая неудача — одно и то же исключение.

    ⚠️ Причина наружу НЕ различается («просрочен» против «подделан»): различие полезно
    только тому, кто подбирает.
    """
    raw = str(token or "")
    expires_str, _, signature = raw.partition(".")
    if not signature:
        raise OwnershipError("токен владения не предъявлен или испорчен")
    try:
        expires_at = int(expires_str)
    except ValueError as exc:
        raise OwnershipError("токен владения испорчен") from exc
    expected = _sign(workspace_id, user_id, expires_at)
    if not hmac.compare_digest(expected, signature):
        raise OwnershipError("токен владения не подошёл")
    if expires_at < int(time.time()):
        raise OwnershipError("токен владения не подошёл")
