"""Email-подтверждение: регистрация с кодом + OTP при входе.

Логика AuthService тестируется без БД/Redis/SMTP — фейковые cache/sender/
profile-source. Реальную доставку кода проверяет E2E/live-SMTP.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.services.profile.application.auth_service import OTP_NAMESPACE, AuthService
from service.services.profile.application.dto import (
    LoginRequest,
    RegisterRequest,
    ResendRequest,
    VerifyRequest,
)
from service.services.profile.application.email_codes import (
    codes_match,
    generate_numeric_code,
    hash_code,
)
from service.settings import AuthConfig, EmailConfig


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #
class FakeUser:
    def __init__(self, email, password_hash, email_verified=False):
        self.id = uuid4()
        self.email = email
        self.password_hash = password_hash
        self.email_verified = email_verified


class FakeProfileService:
    def __init__(self):
        self.users: dict[str, FakeUser] = {}

    async def fetch_user_profile_by_email(self, email):
        return self.users.get(email)

    def verify_password(self, password, password_hash):
        return password_hash == f"hash:{password}"

    async def create_new_user(self, email, password, consent_version=None, **kwargs):
        user = FakeUser(email, f"hash:{password}", email_verified=False)
        user.consent_version = consent_version
        self.users[email] = user
        return user

    async def update_password(self, user_id, email, password):
        self.users[email].password_hash = f"hash:{password}"

    async def record_consent(self, user_id, email, consent_version):
        self.users[email].consent_version = consent_version

    async def mark_email_verified(self, user_id, email):
        self.users[email].email_verified = True


class FakeCache:
    def __init__(self):
        self.store: dict = {}

    async def set_json(self, namespace, key, value, ttl_seconds=None):
        self.store[(namespace, key)] = value

    async def get_json(self, namespace, key):
        return self.store.get((namespace, key))

    async def invalidate(self, namespace, key):
        self.store.pop((namespace, key), None)


class FakeSender:
    def __init__(self):
        self.calls: list[dict] = []

    async def send(self, *, email, code, purpose):
        self.calls.append({"email": email, "code": code, "purpose": purpose})

    @property
    def last_code(self):
        return self.calls[-1]["code"] if self.calls else None


class FakeAuthRepo:
    async def create_session(self, user_session):
        return user_session  # .token уже проставлен _create_jwt


def _auth_config() -> AuthConfig:
    return AuthConfig(
        auth_mode="dev",
        secret="unit-test-secret-000000000000000000",
        algorithm="HS256",
        jwt_exp_hours=24,
    )


def _make_service(profile=None, cache=None, sender=None):
    return AuthService(
        _auth_config(),
        FakeAuthRepo(),
        profile or FakeProfileService(),
        email_config=EmailConfig(),
        cache=cache if cache is not None else FakeCache(),
        code_sender=sender or FakeSender(),
    )


# --------------------------------------------------------------------------- #
# email_codes (pure helpers)                                                   #
# --------------------------------------------------------------------------- #
def test_generate_numeric_code_length_and_digits():
    code = generate_numeric_code(6)
    assert len(code) == 6 and code.isdigit()


def test_generate_numeric_code_clamps_bounds():
    assert len(generate_numeric_code(1)) == 4  # нижняя граница
    assert len(generate_numeric_code(99)) == 12  # верхняя граница


def test_code_hash_matches_and_rejects():
    h = hash_code("123456", "secret")
    assert codes_match("123456", "secret", h)
    assert not codes_match("000000", "secret", h)
    assert not codes_match("123456", "secret", "")


# --------------------------------------------------------------------------- #
# register                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_register_creates_unverified_and_sends_code():
    profile, sender = FakeProfileService(), FakeSender()
    svc = _make_service(profile=profile, sender=sender)

    res = await svc.register_user(
        "ua",
        RegisterRequest(
            email="new@example.com", password="passw0rd1", consent_pd=True, consent_transfer=True
        ),
    )

    assert res.status == "code_sent"
    assert profile.users["new@example.com"].email_verified is False
    assert sender.calls and sender.calls[-1]["purpose"] == "register"


@pytest.mark.asyncio
async def test_register_weak_password_rejected():
    svc = _make_service()
    # Проходит DTO (>=8 символов), но нарушает политику: только цифры, без буквы.
    with pytest.raises(HTTPException) as exc:
        await svc.register_user(
            "ua",
            RegisterRequest(
                email="x@example.com", password="12345678", consent_pd=True, consent_transfer=True
            ),
        )
    assert exc.value.detail["code"] == "weak_password"


@pytest.mark.asyncio
async def test_register_existing_verified_conflicts():
    profile = FakeProfileService()
    profile.users["taken@example.com"] = FakeUser(
        "taken@example.com", "hash:x", email_verified=True
    )
    svc = _make_service(profile=profile)
    with pytest.raises(HTTPException) as exc:
        await svc.register_user(
            "ua",
            RegisterRequest(
                email="taken@example.com",
                password="passw0rd1",
                consent_pd=True,
                consent_transfer=True,
            ),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "email_already_exists"


@pytest.mark.asyncio
async def test_reregister_unverified_updates_password_and_resends():
    profile, sender = FakeProfileService(), FakeSender()
    profile.users["pending@example.com"] = FakeUser(
        "pending@example.com", "hash:old", email_verified=False
    )
    svc = _make_service(profile=profile, sender=sender)

    await svc.register_user(
        "ua",
        RegisterRequest(
            email="pending@example.com",
            password="newpass123",
            consent_pd=True,
            consent_transfer=True,
        ),
    )

    assert profile.users["pending@example.com"].password_hash == "hash:newpass123"
    assert sender.last_code is not None


# --------------------------------------------------------------------------- #
# login                                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_login_correct_password_sends_code_no_session():
    profile, sender = FakeProfileService(), FakeSender()
    profile.users["u@example.com"] = FakeUser(
        "u@example.com", "hash:passw0rd1", email_verified=True
    )
    svc = _make_service(profile=profile, sender=sender)

    res = await svc.login("ua", LoginRequest(email="u@example.com", password="passw0rd1"))

    assert res.status == "code_sent"
    assert sender.calls[-1]["purpose"] == "login"


@pytest.mark.asyncio
async def test_login_wrong_password_raises_invalid_credentials():
    profile = FakeProfileService()
    profile.users["u@example.com"] = FakeUser(
        "u@example.com", "hash:passw0rd1", email_verified=True
    )
    svc = _make_service(profile=profile)
    with pytest.raises(HTTPException) as exc:
        await svc.login("ua", LoginRequest(email="u@example.com", password="nope1234"))
    assert exc.value.detail["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_unknown_user_raises_invalid_credentials():
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.login("ua", LoginRequest(email="ghost@example.com", password="passw0rd1"))
    assert exc.value.detail["code"] == "invalid_credentials"


# --------------------------------------------------------------------------- #
# verify                                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_verify_valid_code_marks_verified_and_returns_jwt():
    profile, sender, cache = FakeProfileService(), FakeSender(), FakeCache()
    svc = _make_service(profile=profile, sender=sender, cache=cache)
    await svc.register_user(
        "ua",
        RegisterRequest(
            email="v@example.com", password="passw0rd1", consent_pd=True, consent_transfer=True
        ),
    )
    code = sender.last_code

    res = await svc.verify_code("ua", VerifyRequest(email="v@example.com", code=code))

    assert res.jwt
    assert profile.users["v@example.com"].email_verified is True
    # Код одноразовый — из хранилища удалён.
    assert cache.store.get((OTP_NAMESPACE, "v@example.com")) is None


@pytest.mark.asyncio
async def test_verify_invalid_code_rejected():
    sender, cache = FakeSender(), FakeCache()
    svc = _make_service(sender=sender, cache=cache)
    await svc.register_user(
        "ua",
        RegisterRequest(
            email="v2@example.com", password="passw0rd1", consent_pd=True, consent_transfer=True
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await svc.verify_code("ua", VerifyRequest(email="v2@example.com", code="000000"))
    assert exc.value.detail["code"] == "invalid_code"


@pytest.mark.asyncio
async def test_verify_without_code_is_expired():
    svc = _make_service()  # ничего не отправляли → нет записи в cache
    with pytest.raises(HTTPException) as exc:
        await svc.verify_code("ua", VerifyRequest(email="none@example.com", code="123456"))
    assert exc.value.detail["code"] == "code_expired"


# --------------------------------------------------------------------------- #
# resend + readiness                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_resend_only_for_existing_user():
    profile, sender = FakeProfileService(), FakeSender()
    profile.users["known@example.com"] = FakeUser(
        "known@example.com", "hash:x", email_verified=True
    )
    svc = _make_service(profile=profile, sender=sender)

    await svc.resend_code("ua", ResendRequest(email="known@example.com"))
    assert sender.calls and sender.calls[-1]["email"] == "known@example.com"

    # Неизвестный адрес — код не шлём (не палим наличие), но ответ обобщённый.
    res = await svc.resend_code("ua", ResendRequest(email="ghost@example.com"))
    assert res.status == "code_sent"
    assert all(c["email"] != "ghost@example.com" for c in sender.calls)


@pytest.mark.asyncio
async def test_verification_unavailable_without_cache():
    svc = _make_service(cache=None)
    # cache=None → _make_service подставит FakeCache; форсим None напрямую.
    svc.cache = None
    with pytest.raises(HTTPException) as exc:
        await svc.register_user(
            "ua",
            RegisterRequest(
                email="a@example.com", password="passw0rd1", consent_pd=True, consent_transfer=True
            ),
        )
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "verification_unavailable"
