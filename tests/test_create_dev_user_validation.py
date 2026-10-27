"""Dev fixtures must obey the same identity contract as normal registration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def _helper():
    path = Path(__file__).resolve().parents[1] / "scripts" / "create_dev_user.py"
    spec = importlib.util.spec_from_file_location("create_dev_user_validation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["invalid", "fixture@example.invalid", "private@example.test"])
async def test_invalid_fixture_email_is_rejected_before_database_access(email, monkeypatch, capsys):
    from service.infrastructure.database import postgresql

    connector = Mock(side_effect=AssertionError("must_not_open_database"))
    monkeypatch.setattr(postgresql, "PgConnector", connector)
    with pytest.raises(SystemExit) as error:
        await _helper()._run(email, "SafePassword123")
    assert error.value.code == 2
    connector.assert_not_called()
    output = capsys.readouterr().out
    assert "контракту регистрации" in output
    assert email not in output
    assert "SafePassword123" not in output


@pytest.mark.asyncio
async def test_valid_fixture_email_uses_normalized_registration_identity(monkeypatch, capsys):
    from service import settings
    from service.infrastructure.database import postgresql
    from service.services.profile.persistence import profile_repository

    connector = Mock(return_value=object())
    repository = SimpleNamespace(
        fetch_user_by_email=AsyncMock(return_value=SimpleNamespace(id="fixture-owned")),
        update_password_hash=AsyncMock(),
        set_email_verified=AsyncMock(),
    )
    monkeypatch.setattr(settings, "Config", lambda: SimpleNamespace(pg=None))
    monkeypatch.setattr(postgresql, "PgConnector", connector)
    monkeypatch.setattr(profile_repository, "ProfileRepository", lambda _: repository)
    await _helper()._run("  Fixture@EXAMPLE.COM  ", "SafePassword123")
    repository.fetch_user_by_email.assert_awaited_once_with("fixture@example.com")
    repository.set_email_verified.assert_awaited_once_with("fixture-owned")
    connector.assert_called_once()
    assert "SafePassword123" not in capsys.readouterr().out
