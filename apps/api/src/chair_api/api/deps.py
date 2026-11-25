"""FastAPI request dependencies for configuration, Redis auth store, and adapters."""

from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.adapters.base import (
    MockOTPProvider,
    OTPProvider,
    PaymentProvider,
    TestModePaymentAdapter,
)
from chair_api.core.auth_store import AuthStore
from chair_api.core.config import Settings, get_settings
from chair_api.core.errors import ChairAPIError
from chair_api.db.session import get_db_session


def get_app_settings(request: Request) -> Settings:
    """Return Settings bound to the FastAPI app instance."""
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings if settings is not None else get_settings()


def get_auth_store(request: Request) -> AuthStore:
    """Return the AuthStore initialized during app lifespan."""
    store: AuthStore | None = getattr(request.app.state, "auth_store", None)
    if store is None:
        raise ChairAPIError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_STORE_UNAVAILABLE",
            message="Authentication store is not initialized.",
        )
    return store


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
AuthStoreDep = Annotated[AuthStore, Depends(get_auth_store)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_otp_provider(settings: SettingsDep) -> OTPProvider:
    """Resolve configured OTP delivery/verification adapter."""
    if settings.auth_otp_provider == "mock":
        if settings.app_env in ("staging", "production"):
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="OTP_PROVIDER_MISCONFIGURED",
                message=f"Mock OTP adapter is disabled in {settings.app_env}.",
            )
        return MockOTPProvider()

    raise ChairAPIError(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="OTP_PROVIDER_UNCONFIGURED",
        message="Configured OTP provider credentials are not provisioned in this environment.",
    )


OTPProviderDep = Annotated[OTPProvider, Depends(get_otp_provider)]


def get_payment_provider(settings: SettingsDep) -> PaymentProvider:
    """Resolve configured payment order/webhook adapter."""
    if settings.payment_provider == "test_mode":
        if settings.app_env in ("staging", "production") or not settings.payment_test_mode:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="PAYMENT_PROVIDER_MISCONFIGURED",
                message=f"Test payment adapter is disabled in {settings.app_env}.",
            )
        return TestModePaymentAdapter()

    raise ChairAPIError(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="PAYMENT_PROVIDER_UNCONFIGURED",
        message="Razorpay merchant credentials are not configured in this environment.",
    )


PaymentProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]
