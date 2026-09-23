import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from service.composition.state import get_auth_service, get_optional_redis_client
from service.services.profile.application.auth_service import AuthService
from service.services.profile.presentation.routers.auth_api.schemas import (
    CodeChallengeResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    ResendRequest,
    VerifyRequest,
)
from service.settings import config
from service.shared.security.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/auth/v1")

# Anti-bruteforce/anti-mass-registration limits, keyed by client IP.
_AUTH_RATE_LIMITS = {"rpm": 10, "rph": 50, "rpd": 300}
# Проверок кода на один email (анти-брутфорс OTP).
_VERIFY_EMAIL_LIMITS = {"rpm": 5, "rph": 20, "rpd": 50}
# Повторных отправок на один email (кулдаун + суточный кап).
_RESEND_EMAIL_LIMITS = {"rpm": 1, "rph": 5, "rpd": 20}


async def _enforce_auth_rate_limit(request: Request, redis_client: Any, scope: str) -> None:
    client_ip = request.client.host if request.client else "unknown"
    limiter = RateLimiter(redis_client, key_prefix=f"auth:{scope}")
    result = await limiter.check(identity=client_ip, limits=_AUTH_RATE_LIMITS, now=time.time())
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts, please try again later",
            headers={"Retry-After": str(result.retry_after)},
        )


async def _enforce_email_limit(
    redis_client: Any, email: str, scope: str, limits: dict, code: str, message: str
) -> None:
    """Пер-email лимит (кулдаун повтора / кап проверок). Fail-open к Redis."""
    limiter = RateLimiter(redis_client, key_prefix=f"auth:{scope}")
    result = await limiter.check(identity=email.strip().lower(), limits=limits, now=time.time())
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail={"code": code, "message": message},
            headers={"Retry-After": str(result.retry_after)},
        )


def _set_auth_cookie(response: Response, token: str) -> None:
    secure_cookie = not config.auth.dev_mode
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="strict" if secure_cookie else "lax",
        max_age=int(config.auth.jwt_exp_hours * 3600),
        path="/",
    )


@auth_router.post(
    path="/register",
    response_model=CodeChallengeResponse,
    summary="Register and send email confirmation code",
    description="Create an account and email a confirmation code. Finish via /verify.",
)
async def register(
    request_body: Annotated[RegisterRequest, Body],
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> CodeChallengeResponse:
    await _enforce_auth_rate_limit(request, redis_client, "register")
    user_agent = request.headers.get("user-agent", "unknown")
    return await service.register_user(user_agent, request_body)


@auth_router.post(
    path="/login",
    response_model=CodeChallengeResponse,
    summary="Verify password and send one-time login code",
    description="Check the password and email a one-time code (OTP). Finish via /verify.",
)
async def login(
    request_body: Annotated[LoginRequest, Body],
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> CodeChallengeResponse:
    await _enforce_auth_rate_limit(request, redis_client, "login")
    user_agent = request.headers.get("user-agent", "unknown")
    return await service.login(user_agent, request_body)


@auth_router.post(
    path="/verify",
    response_model=LoginResponse,
    summary="Verify email code and start a session",
    description="Confirm the emailed code, mark the email verified, and set the auth cookie.",
)
async def verify(
    request_body: Annotated[VerifyRequest, Body],
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> LoginResponse:
    await _enforce_auth_rate_limit(request, redis_client, "verify")
    await _enforce_email_limit(
        redis_client,
        request_body.email,
        "otp_verify",
        _VERIFY_EMAIL_LIMITS,
        code="too_many_attempts",
        message="Too many attempts. Request a new code.",
    )
    user_agent = request.headers.get("user-agent", "unknown")
    user_jwt = await service.verify_code(user_agent, request_body)
    _set_auth_cookie(response, user_jwt.jwt)
    return user_jwt


@auth_router.post(
    path="/resend",
    response_model=CodeChallengeResponse,
    summary="Resend the email confirmation code",
    description="Send a new confirmation code (rate-limited per email).",
)
async def resend(
    request_body: Annotated[ResendRequest, Body],
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> CodeChallengeResponse:
    await _enforce_auth_rate_limit(request, redis_client, "resend")
    await _enforce_email_limit(
        redis_client,
        request_body.email,
        "otp_send",
        _RESEND_EMAIL_LIMITS,
        code="code_resend_too_soon",
        message="Please wait before requesting another code.",
    )
    user_agent = request.headers.get("user-agent", "unknown")
    return await service.resend_code(user_agent, request_body)
