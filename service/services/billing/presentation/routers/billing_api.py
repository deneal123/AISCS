import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from service.composition.state import get_billing_service
from service.models.auth_models import AuthProfile
from service.services.billing.application.billing_service import BillingService
from service.services.billing.application.ports import PaymentWebhookError
from service.shared.security.auth_checker import check_auth

logger = logging.getLogger(__name__)
billing_router = APIRouter(prefix="/api/billing")


class BalanceResponse(BaseModel):
    plan: str
    subscription_remaining: int
    subscription_limit: int | None
    topup: int
    total: int
    reset_date: str | None


class CheckoutRequest(BaseModel):
    kind: Annotated[str, Field(..., description="subscription | topup")]
    plan: str | None = None
    pack_id: str | None = None


class CheckoutResponse(BaseModel):
    checkout_url: str | None = None
    confirmation_token: str | None = None


@billing_router.get("/balance", summary="Get credit balance", response_model=BalanceResponse)
async def get_balance(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BalanceResponse:
    balance = await service.get_balance(str(profile.user_id))
    return BalanceResponse(
        plan=balance.plan,
        subscription_remaining=balance.subscription_remaining,
        subscription_limit=balance.subscription_limit,
        topup=balance.topup,
        total=balance.total,
        reset_date=balance.reset_date.isoformat() if balance.reset_date else None,
    )


@billing_router.get("/packs", summary="List plans and top-up packs")
async def get_packs(
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> dict:
    return service.list_plans_and_packs()


@billing_router.get("/analytics", summary="Usage analytics for charts")
async def get_analytics(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    range: str = "30d",
) -> dict:
    return await service.get_usage_analytics(str(profile.user_id), range_key=range)


@billing_router.get("/history", summary="Billing events (paginated)")
async def get_history(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    limit: int = 20,
    offset: int = 0,
    kind: str | None = None,
) -> dict:
    """Страница истории + total. `kind` — категория фильтра (usage/topup/...)."""
    return await service.get_history(str(profile.user_id), limit=limit, offset=offset, kind=kind)


@billing_router.post(
    "/checkout", summary="Create checkout session", response_model=CheckoutResponse
)
async def create_checkout(
    payload: CheckoutRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> CheckoutResponse:
    try:
        result = await service.create_checkout(
            user_id=str(profile.user_id),
            kind=payload.kind,
            plan=payload.plan,
            pack_id=payload.pack_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PaymentWebhookError as exc:
        # Провайдер не сконфигурирован / не смог создать платёж — это НЕ ошибка
        # клиента. Раньше уходило в голый 500.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return CheckoutResponse(
        checkout_url=result.get("checkout_url"),
        confirmation_token=result.get("confirmation_token"),
    )


@billing_router.post("/webhook", include_in_schema=False)
async def payment_webhook(
    request: Request,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> dict:
    # Raw body нужен для проверки подписи провайдера — НЕ парсим в Pydantic.
    raw = await request.body()
    try:
        return await service.handle_webhook(raw_body=raw, headers=dict(request.headers))
    except PaymentWebhookError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
