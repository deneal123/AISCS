import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from service.composition.state import get_billing_service
from service.models.auth_models import AuthProfile
from service.services.admin.presentation.deps import require_admin
from service.services.billing.application.billing_service import BillingService

logger = logging.getLogger(__name__)
admin_billing_router = APIRouter(prefix="/api/admin/billing")

# require_admin теперь двухисточниковый (env-bootstrap ИЛИ DB is_admin) — общий dep.
__all__ = ["admin_billing_router", "require_admin"]


class PricingUpsertRequest(BaseModel):
    provider: Annotated[str, Field(default="", description="Провайдер; пусто — общий тариф")]
    model_id: Annotated[str, Field(..., description="Идентификатор модели")]
    price_in_rub_per_1k: Annotated[float, Field(..., ge=0, description="₽ за 1K prompt-токенов")]
    price_out_rub_per_1k: Annotated[
        float, Field(..., ge=0, description="₽ за 1K completion-токенов")
    ]
    margin_override: float | None = None
    model_class: str | None = None


@admin_billing_router.get("/pricing", summary="List model pricing registry")
async def list_pricing(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> dict:
    return await service.list_pricing()


@admin_billing_router.put("/pricing", summary="Upsert model price")
async def upsert_pricing(
    payload: PricingUpsertRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> dict:
    return await service.set_pricing(
        provider=payload.provider,
        model_id=payload.model_id,
        price_in=payload.price_in_rub_per_1k,
        price_out=payload.price_out_rub_per_1k,
        margin_override=payload.margin_override,
        model_class=payload.model_class,
        updated_by=str(admin.user_id),
    )


@admin_billing_router.delete("/pricing/{model_id:path}", summary="Delete model price")
async def delete_pricing(
    model_id: str,
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    provider: str = "",
) -> dict:
    return await service.delete_pricing(model_id=model_id, provider=provider)


@admin_billing_router.get("/reconcile", summary="Actual margin vs cost (loss guard)")
async def reconcile(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    range: str = "30d",
) -> dict:
    return await service.reconcile(range_key=range)
