"""Согласия на письма: тумблер в профиле + отписка по ссылке.

Проверяется ровно то, что легко сломать незаметно:

* выключение всех писем ОТЗЫВАЕТ согласие на рекламу, а не усыпляет его;
* частичный PATCH не гасит второе согласие;
* отписка идёт через сервис и инвалидирует кэш профиля (иначе профиль ещё 15 минут
  показывал бы «письма включены»);
* тумблер рекламы не обещает писем, которых рассылка всё равно не отправит.
"""

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from service.models.profile_models import UserProfileLogic
from service.services.profile.application.dto import UpdateNotificationPrefsCommand
from service.services.profile.application.mappers import to_profile_overview_result
from service.services.profile.application.profile_service import ProfileService
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.settings import ProfileConfig


class InMemoryCache:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], dict] = {}
        self.invalidated: list[tuple[str, str]] = []

    async def set_json(self, ns: str, key: str, payload: dict, ttl_seconds=None) -> None:
        self.store[(ns, key)] = dict(payload)

    async def get_json(self, ns: str, key: str) -> dict | None:
        item = self.store.get((ns, key))
        return dict(item) if item is not None else None

    async def invalidate(self, ns: str, key: str) -> None:
        self.invalidated.append((ns, key))
        self.store.pop((ns, key), None)


class FakeRepo:
    """Повторяет семантику CASE из ProfileRepository.update_email_preferences."""

    def __init__(self, user: UserProfileLogic) -> None:
        self.user = user
        self.calls: list[tuple[bool | None, bool | None]] = []

    async def fetch_user_profile(self, user_id: str) -> UserProfileLogic | None:
        return self.user if str(self.user.id) == str(user_id) else None

    async def update_email_preferences(
        self, user_id: str, marketing: bool | None = None, service: bool | None = None
    ) -> UserProfileLogic:
        self.calls.append((marketing, service))
        now = datetime.now(UTC)
        updates: dict[str, datetime | None] = {}
        if marketing is not None:
            updates["marketing_consent_at"] = (
                (self.user.marketing_consent_at or now) if marketing else None
            )
        if service is not None:
            updates["unsubscribed_at"] = None if service else (self.user.unsubscribed_at or now)
        self.user = self.user.model_copy(update=updates)
        return self.user


def _user(**overrides) -> UserProfileLogic:
    now = datetime.now(UTC)
    return UserProfileLogic(
        id=uuid.uuid4(),
        email="pref@example.com",
        password_hash="hash",
        created_at=now,
        updated_at=now,
        **overrides,
    )


def _service(repo: FakeRepo, cache: InMemoryCache) -> ProfileService:
    return ProfileService(ProfileConfig(base_available_launches=3), repo, cache=cache)


###############################################################################
# Выключить всё = отозвать согласие на рекламу, а не усыпить его              #
###############################################################################


def test_disabling_all_mail_also_withdraws_marketing_consent() -> None:
    """Иначе согласие «спит»: вернув сервисные письма, человек снова получал бы рекламу."""
    assert ProfileService._resolve_email_prefs(None, False) == (False, False)
    # Даже явное «рекламу оставить включённой» не переживает выключение всех писем.
    assert ProfileService._resolve_email_prefs(True, False) == (False, False)


def test_partial_patch_does_not_touch_the_other_consent() -> None:
    """Непереданное поле = None = «не трогать». Иначе один тумблер гасил бы второй."""
    assert ProfileService._resolve_email_prefs(True, None) == (True, None)
    assert ProfileService._resolve_email_prefs(None, True) == (None, True)


@pytest.mark.asyncio
async def test_reenabling_service_does_not_resurrect_marketing() -> None:
    """Главный сценарий: отписался → вернул сервисные письма → рекламы БЫТЬ НЕ ДОЛЖНО."""
    user = _user(marketing_consent_at=datetime.now(UTC))
    repo, cache = FakeRepo(user), InMemoryCache()
    service = _service(repo, cache)

    await service.unsubscribe_all(user.id)
    assert repo.user.unsubscribed_at is not None
    assert repo.user.marketing_consent_at is None, "отписка обязана отозвать согласие"

    await service.update_email_preferences(
        UpdateNotificationPrefsCommand(user_id=user.id, service=True)
    )
    assert repo.user.unsubscribed_at is None, "сервисные письма вернулись"
    assert repo.user.marketing_consent_at is None, "а реклама — нет: согласие отозвано"


###############################################################################
# Кэш профиля                                                                 #
###############################################################################


@pytest.mark.asyncio
async def test_toggle_refreshes_profile_cache() -> None:
    """Профиль живёт в Redis 15 минут: без инвалидации тумблер отскакивал бы назад."""
    user = _user()
    repo, cache = FakeRepo(user), InMemoryCache()
    service = _service(repo, cache)

    await service.fetch_user_profile(user.id)  # прогреть кэш
    await service.update_email_preferences(
        UpdateNotificationPrefsCommand(user_id=user.id, marketing=True)
    )

    cached = await cache.get_json("profile:id:v2", str(user.id))
    assert cached is not None
    assert cached["marketing_consent_at"] is not None, "в кэше осталось старое согласие"


def test_cached_profile_namespace_is_versioned() -> None:
    """Схема кэшируемого профиля изменилась → старые записи обязаны обесцениться.

    Без версии Pydantic подставил бы отсутствующим полям None, то есть «согласия нет», и
    до 15 минут профиль показывал бы про согласие чужую правду.
    """
    from service.services.profile.application import profile_service as mod

    assert mod.PROFILE_BY_ID_NAMESPACE.endswith(":v2")
    assert mod.PROFILE_BY_EMAIL_NAMESPACE.endswith(":v2")


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent() -> None:
    user = _user(marketing_consent_at=datetime.now(UTC))
    repo, cache = FakeRepo(user), InMemoryCache()
    service = _service(repo, cache)

    assert await service.unsubscribe_all(user.id) is True
    assert await service.unsubscribe_all(user.id) is False, "повторная отписка — не событие"


###############################################################################
# Тумблер не должен обещать писем, которых рассылка не отправит               #
###############################################################################


def test_marketing_toggle_reads_false_while_unsubscribed() -> None:
    """`unsubscribed_at` гасит ВСЁ, включая рекламу, — даже если согласие формально есть."""
    now = datetime.now(UTC)
    profile = _user(marketing_consent_at=now, unsubscribed_at=now)
    result = to_profile_overview_result(profile)
    assert result.service_emails is False
    assert result.marketing_emails is False


def test_fresh_user_gets_service_mail_but_no_marketing() -> None:
    result = to_profile_overview_result(_user())
    assert result.service_emails is True, "письма о состоянии аккаунта — по умолчанию да"
    assert result.marketing_emails is False, "реклама — только по отдельному согласию"


###############################################################################
# Идемпотентный повтор не должен переписывать дату исходного согласия          #
###############################################################################


def test_repository_preserves_original_consent_timestamp() -> None:
    """«Включено → включено» не двигает метку: иначе повтор подделывал бы дату согласия.

    Проверяем по исходнику: метка ставится через CASE ... IS NULL THEN NOW(), а не
    безусловным NOW().
    """
    source = inspect.getsource(ProfileRepository.update_email_preferences)
    assert "case(" in source
    assert "User.marketing_consent_at.is_(None)" in source
    assert "User.unsubscribed_at.is_(None)" in source


def test_unsubscribe_link_goes_through_the_service() -> None:
    """Сырой UPDATE в обход сервиса оставлял бы в кэше «письма включены»."""
    from service.services.notifications import api, notification_service

    assert not hasattr(notification_service.NotificationService, "unsubscribe")
    assert "unsubscribe_all" in inspect.getsource(api.unsubscribe)
