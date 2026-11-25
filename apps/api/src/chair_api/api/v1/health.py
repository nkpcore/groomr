"""Health, readiness, and non-secret platform metadata endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from chair_api import __version__
from chair_api.core.config import Settings, get_settings

router = APIRouter()


class DependencyCheck(BaseModel):
    status: Literal["ok", "unavailable"]
    detail: str | None = None


class HealthChecks(BaseModel):
    database: DependencyCheck
    postgis: DependencyCheck
    redis: DependencyCheck


class AdapterModes(BaseModel):
    auth_otp: str
    payments: str
    storage: str
    maps: str
    notifications: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    timestamp_utc: datetime
    booking_hold_ttl_seconds: int
    adapters: AdapterModes
    checks: HealthChecks


class PlatformMetaResponse(BaseModel):
    brand: str
    currency: str
    supported_locales: list[str]
    booking_hold_ttl_seconds: int
    verification_badge_disclaimer: str


async def check_postgres_and_postgis(database_url: str) -> tuple[DependencyCheck, DependencyCheck]:
    """Probe PostgreSQL connectivity and PostGIS extension availability."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with asyncio.timeout(1.5):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                db_check = DependencyCheck(status="ok")
                try:
                    res = await conn.execute(text("SELECT PostGIS_Version()"))
                    postgis_ver = res.scalar_one_or_none()
                    postgis_check = DependencyCheck(
                        status="ok",
                        detail=f"postgis:{postgis_ver}" if postgis_ver else "enabled",
                    )
                except Exception as exc:  # pragma: no cover - requires live DB without postgis
                    postgis_check = DependencyCheck(
                        status="unavailable",
                        detail=type(exc).__name__,
                    )
        return db_check, postgis_check
    except Exception as exc:
        err = f"{type(exc).__name__}: unavailable"
        return DependencyCheck(status="unavailable", detail=err), DependencyCheck(
            status="unavailable",
            detail="database_unavailable",
        )
    finally:
        await engine.dispose()


async def check_redis(redis_url: str) -> DependencyCheck:
    """Probe Redis PING within a short bounded timeout."""
    client: Redis = Redis.from_url(redis_url, socket_connect_timeout=1.0, socket_timeout=1.0)
    try:
        async with asyncio.timeout(1.5):
            pong = await client.ping()
            return DependencyCheck(status="ok" if pong else "unavailable")
    except Exception as exc:
        return DependencyCheck(status="unavailable", detail=type(exc).__name__)
    finally:
        await client.aclose()


async def build_health_payload(settings: Settings) -> HealthResponse:
    db_task = check_postgres_and_postgis(settings.database_url)
    redis_task = check_redis(settings.redis_url)
    (db_check, postgis_check), redis_check = await asyncio.gather(db_task, redis_task)

    all_ok = (
        db_check.status == "ok"
        and postgis_check.status == "ok"
        and redis_check.status == "ok"
    )
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        timestamp_utc=datetime.now(UTC),
        booking_hold_ttl_seconds=settings.booking_hold_ttl_seconds,
        adapters=AdapterModes(
            auth_otp=settings.auth_otp_provider,
            payments=settings.payment_provider,
            storage=settings.storage_provider,
            maps=settings.maps_provider,
            notifications=settings.notification_provider,
        ),
        checks=HealthChecks(
            database=db_check,
            postgis=postgis_check,
            redis=redis_check,
        ),
    )


@router.get("/health", response_model=HealthResponse, summary="Service & dependency health")
async def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:  # noqa: B008
    """Return service status and live DB/PostGIS/Redis probe results without faking health."""
    return await build_health_payload(settings)


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Strict readiness probe (503 when dependencies are down)",
)
async def get_readiness(
    response: Response,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> HealthResponse:
    payload = await build_health_payload(settings)
    if payload.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@router.get("/meta", response_model=PlatformMetaResponse, summary="Public platform configuration")
async def get_meta(settings: Settings = Depends(get_settings)) -> PlatformMetaResponse:  # noqa: B008
    return PlatformMetaResponse(
        brand="CHAIR",
        currency="INR",
        supported_locales=["en", "hi"],
        booking_hold_ttl_seconds=settings.booking_hold_ttl_seconds,
        verification_badge_disclaimer=(
            "CHAIR VERIFIED is an independent platform verification badge, "
            "not government certification or statutory licensing."
        ),
    )
