"""Unit tests for health, readiness, and platform metadata endpoints."""

from fastapi.testclient import TestClient

from chair_api.api.v1 import health as health_module
from chair_api.core.config import Settings
from chair_api.main import create_app


def test_health_reports_ok_when_dependencies_respond(monkeypatch) -> None:
    async def fake_pg(_url: str):
        return (
            health_module.DependencyCheck(status="ok"),
            health_module.DependencyCheck(status="ok", detail="postgis:3.4"),
        )

    async def fake_redis(_url: str):
        return health_module.DependencyCheck(status="ok")

    monkeypatch.setattr(health_module, "check_postgres_and_postgis", fake_pg)
    monkeypatch.setattr(health_module, "check_redis", fake_redis)

    app = create_app(Settings(app_env="test"))
    with TestClient(app) as client:
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["service"] == "chair-api"
        assert body["booking_hold_ttl_seconds"] == 300
        assert body["checks"]["postgis"]["status"] == "ok"


def test_readiness_returns_503_when_dependencies_unavailable(monkeypatch) -> None:
    async def fake_pg(_url: str):
        return (
            health_module.DependencyCheck(status="unavailable", detail="ConnectionRefused"),
            health_module.DependencyCheck(status="unavailable", detail="database_unavailable"),
        )

    async def fake_redis(_url: str):
        return health_module.DependencyCheck(status="unavailable", detail="ConnectionError")

    monkeypatch.setattr(health_module, "check_postgres_and_postgis", fake_pg)
    monkeypatch.setattr(health_module, "check_redis", fake_redis)

    app = create_app(Settings(app_env="test"))
    with TestClient(app) as client:
        res = client.get("/api/v1/health/ready")
        assert res.status_code == 503
        assert res.json()["status"] == "degraded"


def test_meta_and_openapi_expose_v1_contract() -> None:
    app = create_app(Settings(app_env="test"))
    with TestClient(app) as client:
        meta = client.get("/api/v1/meta")
        assert meta.status_code == 200
        data = meta.json()
        assert data["brand"] == "CHAIR"
        assert data["currency"] == "INR"
        assert data["supported_locales"] == ["en", "hi"]
        assert "not government certification" in data["verification_badge_disclaimer"]

        openapi = client.get("/api/v1/openapi.json")
        assert openapi.status_code == 200
        assert "/api/v1/health" in openapi.json()["paths"]
