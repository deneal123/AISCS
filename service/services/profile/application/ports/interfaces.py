from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProfileRepositoryPort(Protocol):
    async def fetch_user_profile(self, user_id: str) -> Any | None: ...
    async def fetch_user_by_email(self, email: str) -> Any | None: ...
    # `consent_marketing` — отдельное согласие на маркетинг (миграция 016). Оно
    # передаётся из `profile_service` и принимается репозиторием, но в порт внесено
    # не было: контракт умалчивал о поле, от которого зависит юридическая часть
    # регистрации.
    async def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        consent_version: str | None = None,
        consent_marketing: bool = False,
    ) -> Any: ...
    async def update_user_profile(self, profile: Any) -> Any: ...
    async def set_email_verified(self, user_id: str) -> None: ...
    async def update_password_hash(self, user_id: str, password_hash: str) -> None: ...
    async def record_consent(self, user_id: str, consent_version: str | None) -> None: ...
    async def update_email_preferences(
        self, user_id: str, marketing: bool | None = None, service: bool | None = None
    ) -> Any: ...
    async def delete_user_chat_history(self, user_id: str) -> None: ...


@runtime_checkable
class ProfileCachePort(Protocol):
    async def set_json(
        self, namespace: str, key: str, value: dict, ttl_seconds: int | None = None
    ) -> None: ...
    async def get_json(self, namespace: str, key: str) -> dict | None: ...
    async def invalidate(self, namespace: str, key: str) -> None: ...


@runtime_checkable
class VerificationCodeSenderPort(Protocol):
    """Отправка одноразового кода на email (реализация — Celery/SMTP)."""

    async def send(self, *, email: str, code: str, purpose: str) -> None: ...
