"""Short-lived task/attempt capabilities, never available to model tools."""

import hashlib
import hmac
import time
from functools import lru_cache
from uuid import UUID

import jwt
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from service.shared.harness_protocol import Admission, HarnessFailure
from service.shared.task_contract import ContractModel


class HarnessSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HARNESS__", extra="ignore")
    ide_enabled: bool = False
    ide_commands_enabled: bool = False
    pdf_enabled: bool = False
    dispatch_enabled: bool = True
    prompt_limit: int = Field(default=32768, ge=1024, le=131072)
    completion_limit: int = Field(default=4096, ge=256, le=32768)


@lru_cache
def settings() -> HarnessSettings:
    return HarnessSettings()


def require_dispatch(admission: Admission) -> None:
    """Disabling one surface stops dispatch, not receipts or reconciliation."""
    flags = settings()
    surface_enabled = flags.ide_enabled if admission.surface == "ide" else flags.pdf_enabled
    if not flags.dispatch_enabled or not surface_enabled:
        raise HarnessFailure("dispatch_disabled")


class HarnessOwner(ContractModel):
    task_id: str
    job_id: str
    user_id: str
    thread_id: str
    attempt_id: str
    epoch: int = Field(ge=1)
    project_id: str
    generation: str

    def params(self):
        result = self.model_dump()
        for key in ("task_id", "job_id", "user_id", "thread_id", "attempt_id"):
            result[key] = UUID(result[key])
        return result


def _key() -> bytes:
    from service.settings import config

    secret = str(config.auth.secret).encode()
    if len(secret) < 24:
        raise HarnessFailure()
    return hmac.new(secret, b"gpthub:private-harness:v1", hashlib.sha256).digest()


def issue(owner: HarnessOwner) -> str:
    return jwt.encode(
        {
            **owner.model_dump(),
            "aud": "gpthub-harness-v1",
            "iss": "gpthub-backend",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        },
        _key(),
        algorithm="HS256",
    )


def authorize(token: str) -> HarnessOwner:
    try:
        claims = jwt.decode(
            token,
            _key(),
            algorithms=["HS256"],
            audience="gpthub-harness-v1",
            issuer="gpthub-backend",
            options={"require": ["iat", "exp"]},
        )
        for key in ("aud", "iss", "iat", "exp"):
            claims.pop(key)
        owner = HarnessOwner.model_validate(claims)
        owner.params()
        return owner
    except (ValueError, jwt.PyJWTError, TypeError, KeyError):
        raise HarnessFailure("harness_forbidden") from None
