"""Typed application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRET_MARKERS = ("change-me", "dev-only-", "replace-with-", "insecure")


def _is_weak_secret(value: str) -> bool:
    if len(value.encode("utf-8")) < 32:
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in _INSECURE_SECRET_MARKERS)


class Settings(BaseSettings):
    """Runtime settings for CHAIR API and workers."""

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "chair-api"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str = Field(default="dev-only-insecure-secret-change-me")
    allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:8081,http://127.0.0.1:8081"
    )
    trust_proxy_headers: bool = False

    database_url: str = "postgresql+asyncpg://chair:chair_dev_password@localhost:5432/chair_db"
    test_database_url: str = (
        "postgresql+asyncpg://chair:chair_dev_password@localhost:5432/chair_test_db"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    booking_hold_ttl_seconds: int = Field(default=300, ge=60, le=1800)
    default_search_radius_meters: int = Field(default=5000, ge=500, le=50000)
    max_search_radius_meters: int = Field(default=25000, ge=1000, le=100000)
    enable_demo_seed: bool = True

    auth_otp_provider: Literal["mock", "supabase", "firebase", "msg91"] = "mock"
    jwt_access_ttl_minutes: int = Field(default=30, ge=5, le=120)
    jwt_refresh_ttl_days: int = Field(default=30, ge=1, le=90)
    otp_ttl_seconds: int = Field(default=300, ge=60, le=900)
    otp_request_window_seconds: int = Field(default=900, ge=60, le=3600)
    otp_request_max_per_phone: int = Field(default=5, ge=1, le=20)
    otp_request_max_per_ip: int = Field(default=20, ge=1, le=100)
    otp_verify_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_verify_max_failures_per_window: int = Field(default=10, ge=3, le=50)
    consent_policy_version: str = "v1.0"

    payment_provider: Literal["test_mode", "razorpay"] = "test_mode"
    payment_test_mode: bool = True
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    default_commission_rate_bps: int = Field(default=800, ge=0, le=5000)
    commission_gst_bps: int = Field(default=1800, ge=0, le=5000)

    storage_provider: Literal["local_signed", "s3", "supabase"] = "local_signed"
    local_storage_dir: str = ".storage"
    storage_signing_secret: str = Field(default="dev-only-storage-signing-secret")
    max_upload_size_bytes: int = Field(default=5_242_880, ge=1024, le=20_971_520)

    maps_provider: Literal["local_stub", "google_maps", "mapbox"] = "local_stub"
    notification_provider: Literal["console_outbox", "fcm_smtp"] = "console_outbox"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def sync_database_url(self) -> str:
        """Convert asyncpg URL to psycopg URL for Alembic migrations."""
        if "+asyncpg" in self.database_url:
            return self.database_url.replace("+asyncpg", "+psycopg", 1)
        return self.database_url

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.app_env in ("staging", "production"):
            if self.auth_otp_provider == "mock":
                raise ValueError(f"Mock OTP provider cannot be used in {self.app_env}.")
            if self.payment_provider == "test_mode" or self.payment_test_mode:
                raise ValueError(f"Test payment mode cannot be enabled in {self.app_env}.")
            if _is_weak_secret(self.secret_key):
                raise ValueError(
                    "SECRET_KEY must be a non-placeholder secret of at least 32 bytes."
                )
            if _is_weak_secret(self.storage_signing_secret):
                raise ValueError(
                    "STORAGE_SIGNING_SECRET must be a non-placeholder secret of at least 32 bytes."
                )
            if self.app_env == "production" and self.enable_demo_seed:
                raise ValueError("ENABLE_DEMO_SEED must be disabled in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
