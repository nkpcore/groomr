"""Celery worker configuration and scheduled background tasks."""

from celery import Celery

from chair_api.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "chair_workers",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "expire-stale-slot-holds-every-minute": {
            "task": "chair_api.workers.expire_stale_slot_holds",
            "schedule": 60.0,
        }
    },
)


@celery_app.task(name="chair_api.workers.expire_stale_slot_holds")  # type: ignore[untyped-decorator]
def expire_stale_slot_holds() -> dict[str, str]:
    """Placeholder periodic sweep; Phase 4 wires transactional hold expiration."""
    return {"status": "stubbed_phase_0"}
