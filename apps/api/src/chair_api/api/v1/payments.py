"""Signed payment provider webhook ingestion endpoint."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from chair_api.api.deps import DbSessionDep, PaymentProviderDep, SettingsDep
from chair_api.services.booking_engine import handle_payment_webhook

router = APIRouter()


@router.post("/webhook/{provider}")
async def ingest_payment_webhook(
    provider: str,
    request: Request,
    session: DbSessionDep,
    payment_provider: PaymentProviderDep,
    settings: SettingsDep,
    x_razorpay_signature: Annotated[str, Header(alias="X-Razorpay-Signature")] = "",
) -> dict[str, Any]:
    """Verify HMAC-SHA256 webhook signature and settle idempotently."""
    raw_body = await request.body()
    return await handle_payment_webhook(
        session,
        provider=provider,
        raw_body=raw_body,
        signature=x_razorpay_signature,
        payment_provider=payment_provider,
        settings=settings,
    )
