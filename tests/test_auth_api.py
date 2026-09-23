import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.composition.state import (
    get_auth_service,
    get_optional_redis_client,
    get_profile_service,
)
from service.main import app
from service.models.profile_models import UserProfileLogic
from service.settings import config


class FakeProfileService:
    def __init__(self):
        now = datetime.now(UTC)
        self.user = UserProfileLogic(
            id=uuid.uuid4(),
            email="user@example.com",
            password_hash="hash",
            first_name="A",
            timezone="UTC",
            avatar_url=None,
            available_launches=3,
            created_at=now,
            updated_at=now,
        )

    async def fetch_user_profile_by_email(self, email):
        return self.user

    def verify_password(self, password, password_hash):
        return True


class _FakeOtpAuthService:
    """Двухшаговый логин: /login только шлёт код, сессию открывает /verify."""

    async def login(self, user_agent, request_body):
        return SimpleNamespace(status="code_sent", email=request_body.email)

    async def verify_code(self, user_agent, request_body):
        return SimpleNamespace(jwt="token-123")


def _override_auth(client_overrides):
    client_overrides[get_auth_service] = lambda: _FakeOtpAuthService()
    client_overrides[get_profile_service] = lambda: FakeProfileService()
    client_overrides[get_optional_redis_client] = lambda: None


def _clear_auth(client_overrides):
    for dep in (get_auth_service, get_profile_service, get_optional_redis_client):
        client_overrides.pop(dep, None)


def test_login_sends_code_and_sets_no_cookie():
    """Пароль верный — но сессия ещё НЕ открыта: сначала код на почту.

    Раньше /login сразу ставил куку. С подтверждением email по OTP это стало дырой:
    кука выдавалась до проверки владения почтой. Теперь /login отдаёт code_sent.
    """
    client = TestClient(app)
    _override_auth(app.dependency_overrides)
    try:
        resp = client.post(
            "/api/auth/v1/login", json={"email": "user@example.com", "password": "pass"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "code_sent", "email": "user@example.com"}
        assert "auth_token" not in resp.cookies
    finally:
        _clear_auth(app.dependency_overrides)


def test_verify_sets_cookie():
    """Куку ставит только /verify — после подтверждения кода из письма."""
    client = TestClient(app)
    _override_auth(app.dependency_overrides)
    try:
        resp = client.post(
            "/api/auth/v1/verify", json={"email": "user@example.com", "code": "123456"}
        )
        assert resp.status_code == 200
        assert "auth_token" in resp.cookies
        ck = resp.headers.get("set-cookie")
        assert f"Max-Age={int(config.auth.jwt_exp_hours * 3600)}" in ck
    finally:
        _clear_auth(app.dependency_overrides)
