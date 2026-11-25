"""Live PostgreSQL+PostGIS+Redis integration tests for Phase 3 Partner Ops & Admin Verification."""

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chair_api.core.config import Settings
from chair_api.db.models import (
    AuditLog,
    Inspection,
    SalonDocument,
    UserRoleAssignment,
    VerificationCheck,
)
from chair_api.db.seeds.demo_seed import seed_demo_data
from chair_api.main import create_app

VALID_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00"
    b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
async def phase3_client(
    postgres_test_engine: AsyncEngine,
    tmp_path: object,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings]]:
    """Create FastAPI AsyncClient backed by test Postgres+PostGIS+Redis and temp private storage."""
    test_redis_url = "redis://localhost:6379/15"
    redis_probe = Redis.from_url(test_redis_url, decode_responses=True, socket_connect_timeout=1.0)
    try:
        await redis_probe.ping()
    except Exception as exc:
        await redis_probe.aclose()
        pytest.skip(f"Redis unavailable ({type(exc).__name__}).")
    await redis_probe.aclose()

    session_factory = async_sessionmaker(
        postgres_test_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as s:
        await seed_demo_data(s)

    db_url = postgres_test_engine.url.render_as_string(hide_password=False)
    settings = Settings(
        app_env="test",
        secret_key="phase3-partner-admin-test-secret-min-32-bytes",
        database_url=db_url,
        test_database_url=db_url,
        redis_url=test_redis_url,
        local_storage_dir=str(tmp_path),
        max_upload_size_bytes=2048,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, session_factory, settings


async def _auth_headers(client: AsyncClient, phone_e164: str) -> dict[str, str]:
    req_res = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone_e164})
    assert req_res.status_code == 200, req_res.text
    challenge_id = req_res.json()["challenge_id"]
    ver_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "phone_e164": phone_e164, "otp_code": "123456"},
    )
    assert ver_res.status_code == 200, ver_res.text
    return {"Authorization": f"Bearer {ver_res.json()['access_token']}"}


def _next_target_weekday_ist(weekday: int = 2) -> str:
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    days_ahead = (weekday - now_ist.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now_ist.date() + timedelta(days=days_ahead)).isoformat()


@pytest.mark.asyncio
async def test_partner_onboarding_cross_tenant_idor_and_setup_to_availability(
    phase3_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, _session_factory, _settings = phase3_client
    owner_phone = f"+9196{uuid.uuid4().int % 10**8:08d}"
    intruder_phone = f"+9195{uuid.uuid4().int % 10**8:08d}"
    owner_headers = await _auth_headers(client, owner_phone)
    intruder_headers = await _auth_headers(client, intruder_phone)
    admin_headers = await _auth_headers(client, "+919000000002")

    tag = uuid.uuid4().hex[:6]
    onboard_res = await client.post(
        "/api/v1/partner/salons",
        headers=owner_headers,
        json={
            "legal_name": f"[DEMO] Amber Blade Pvt Ltd {tag}",
            "brand_name": f"[DEMO] Amber Blade {tag}",
            "gstin": "29ABCDE1234F1Z5",
            "pan_masked": "ABCDE****F",
            "branch_name": f"[DEMO] Indiranagar Flagship {tag}",
            "address_line1": "44 12th Main, HAL 2nd Stage",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560038",
            "lat": 12.9718,
            "lng": 77.6412,
            "initial_chair_count": 1,
        },
    )
    assert onboard_res.status_code == 201, onboard_res.text
    salon_id = onboard_res.json()["salon"]["id"]
    branch_id = onboard_res.json()["branch"]["id"]
    assert onboard_res.json()["branch"]["status"] == "DRAFT"

    # Cross-tenant intruder cannot inspect setup, add branch, or configure services.
    assert (
        await client.get(f"/api/v1/partner/branches/{branch_id}/setup", headers=intruder_headers)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/partner/salons/{salon_id}/branches",
            headers=intruder_headers,
            json={
                "name": "Hijack Branch",
                "address_line1": "99 Fake Street",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": "560001",
                "lat": 12.97,
                "lng": 77.59,
            },
        )
    ).status_code == 403

    catalog_res = await client.get("/api/v1/partner/catalog-services", headers=owner_headers)
    assert catalog_res.status_code == 200, catalog_res.text
    catalog_items = catalog_res.json()["items"]
    assert len(catalog_items) >= 1
    catalog_svc_id = catalog_items[0]["id"]

    bs_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/services",
        headers=owner_headers,
        json={
            "service_id": catalog_svc_id,
            "display_name_en": f"Signature Trim {tag}",
            "display_name_hi": f"सिग्नेचर ट्रिम {tag}",
            "price_paise": 59900,
            "duration_minutes": 30,
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 5,
        },
    )
    assert bs_res.status_code == 201, bs_res.text
    bs_id = bs_res.json()["id"]

    # Duplicate catalog service per branch rejected cleanly.
    dup_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/services",
        headers=owner_headers,
        json={
            "service_id": catalog_svc_id,
            "display_name_en": "Duplicate",
            "display_name_hi": "डुप्लीकेट",
            "price_paise": 59900,
            "duration_minutes": 30,
        },
    )
    assert dup_res.status_code == 409

    target_date_str = _next_target_weekday_ist(weekday=2)
    target_weekday = 2
    staff_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/staff",
        headers=owner_headers,
        json={
            "display_name": f"[DEMO] Arjun Verma {tag}",
            "bio": "Precision scissor cut specialist",
            "specializations": ["Haircut", "Fade"],
            "qualified_branch_service_ids": [bs_id],
            "shifts": [
                {
                    "weekday": target_weekday,
                    "start_time": "10:00",
                    "end_time": "13:00",
                    "timezone": "Asia/Kolkata",
                }
            ],
        },
    )
    assert staff_res.status_code == 201, staff_res.text
    staff_id = staff_res.json()["id"]

    hours_res = await client.patch(
        f"/api/v1/partner/branches/{branch_id}/hours",
        headers=owner_headers,
        json={
            "operating_hours": {
                "mon": {"open": "09:30", "close": "21:30"},
                "tue": {"open": "09:30", "close": "21:30"},
                "wed": {"open": "10:00", "close": "13:00"},
                "thu": {"open": "09:30", "close": "21:30"},
                "fri": {"open": "09:30", "close": "21:30"},
                "sat": {"open": "09:00", "close": "21:00"},
                "sun": None,
            }
        },
    )
    assert hours_res.status_code == 200, hours_res.text

    chair2_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/resources",
        headers=owner_headers,
        json={"name": "Chair 2", "resource_type": "BARBER_CHAIR", "is_active": True},
    )
    assert chair2_res.status_code == 201, chair2_res.text

    setup_res = await client.get(
        f"/api/v1/partner/branches/{branch_id}/setup", headers=owner_headers
    )
    assert setup_res.status_code == 200, setup_res.text
    setup_json = setup_res.json()
    assert len(setup_json["branch_services"]) == 1
    assert len(setup_json["staff"]) == 1
    assert len(setup_json["resources"]) == 2

    # Admin activates branch so customer discovery & availability include it.
    gov_res = await client.patch(
        f"/api/v1/admin/branches/{branch_id}/governance",
        headers=admin_headers,
        json={"status": "ACTIVE"},
    )
    assert gov_res.status_code == 200, gov_res.text

    avail_res = await client.get(
        f"/api/v1/branches/{branch_id}/availability",
        params={"date": target_date_str, "service_ids": bs_id},
    )
    assert avail_res.status_code == 200, avail_res.text
    slots_before = avail_res.json()["slots"]
    assert len(slots_before) >= 2
    first_slot = slots_before[0]

    # Partner adds a schedule block over the first slot -> availability drops that slot.
    block_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/blocks",
        headers=owner_headers,
        json={
            "staff_id": staff_id,
            "block_type": "BREAK",
            "start_at": first_slot["start_at"],
            "end_at": first_slot["end_at"],
            "reason": "Lunch break",
        },
    )
    assert block_res.status_code == 201, block_res.text
    block_id = block_res.json()["id"]

    avail_blocked = await client.get(
        f"/api/v1/branches/{branch_id}/availability",
        params={"date": target_date_str, "service_ids": bs_id},
    )
    assert first_slot["start_at"] not in {s["start_at"] for s in avail_blocked.json()["slots"]}

    del_res = await client.delete(
        f"/api/v1/partner/branches/{branch_id}/blocks/{block_id}", headers=owner_headers
    )
    assert del_res.status_code == 200
    avail_restored = await client.get(
        f"/api/v1/branches/{branch_id}/availability",
        params={"date": target_date_str, "service_ids": bs_id},
    )
    assert first_slot["start_at"] in {s["start_at"] for s in avail_restored.json()["slots"]}


@pytest.mark.asyncio
async def test_kyc_upload_magic_bytes_signed_urls_and_admin_review(
    phase3_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, session_factory, _settings = phase3_client
    owner_phone = f"+9194{uuid.uuid4().int % 10**8:08d}"
    other_phone = f"+9193{uuid.uuid4().int % 10**8:08d}"
    owner_headers = await _auth_headers(client, owner_phone)
    other_headers = await _auth_headers(client, other_phone)
    admin_headers = await _auth_headers(client, "+919000000002")

    onboard_res = await client.post(
        "/api/v1/partner/salons",
        headers=owner_headers,
        json={
            "legal_name": "[DEMO] KYC Salon Legal",
            "brand_name": "[DEMO] KYC Salon",
            "branch_name": "[DEMO] Bandra West Studio",
            "address_line1": "101 Pali Hill",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400050",
            "lat": 19.0607,
            "lng": 72.8362,
        },
    )
    assert onboard_res.status_code == 201
    branch_id = onboard_res.json()["branch"]["id"]

    # Spoofed magic bytes rejected with 422.
    spoof_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/documents",
        headers=owner_headers,
        json={
            "document_type": "OWNER_ID",
            "mime_type": "image/png",
            "content_base64": base64.b64encode(b"#!/bin/sh echo evil").decode("ascii"),
        },
    )
    assert spoof_res.status_code == 422
    assert spoof_res.json()["error"]["code"] == "INVALID_UPLOAD"

    # Oversize PNG rejected (> 2048 test limit).
    big_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/documents",
        headers=owner_headers,
        json={
            "document_type": "OWNER_ID",
            "mime_type": "image/png",
            "content_base64": base64.b64encode(VALID_TINY_PNG + b"A" * 2500).decode("ascii"),
        },
    )
    assert big_res.status_code == 422
    assert big_res.json()["error"]["code"] == "INVALID_UPLOAD"

    # Valid tiny PNG succeeds and stores privately.
    ok_res = await client.post(
        f"/api/v1/partner/branches/{branch_id}/documents",
        headers=owner_headers,
        json={
            "document_type": "SHOP_ESTABLISHMENT_LICENSE",
            "mime_type": "image/png",
            "content_base64": base64.b64encode(VALID_TINY_PNG).decode("ascii"),
        },
    )
    assert ok_res.status_code == 201, ok_res.text
    doc_payload = ok_res.json()
    doc_id = doc_payload["id"]
    signed_url = doc_payload["signed_url"]
    assert "/api/v1/assets/signed?" in signed_url

    # Signed URL security matrix: unauthenticated -> 401, cross-tenant -> 403, tampered -> 403.
    assert (await client.get(signed_url)).status_code == 401
    assert (await client.get(signed_url, headers=other_headers)).status_code == 403

    parsed = urlparse(signed_url)
    qs = parse_qs(parsed.query)
    tampered = f"{parsed.path}?key={qs['key'][0]}&expires={qs['expires'][0]}&sig={'0' * 64}"
    assert (await client.get(tampered, headers=owner_headers)).status_code == 403

    expired = f"{parsed.path}?key={qs['key'][0]}&expires=1&sig={qs['sig'][0]}"
    assert (await client.get(expired, headers=owner_headers)).status_code == 403

    owner_dl = await client.get(signed_url, headers=owner_headers)
    assert owner_dl.status_code == 200
    assert owner_dl.content == VALID_TINY_PNG
    assert owner_dl.headers.get("x-content-type-options") == "nosniff"
    assert "no-store" in owner_dl.headers.get("cache-control", "")

    admin_dl = await client.get(signed_url, headers=admin_headers)
    assert admin_dl.status_code == 200
    assert admin_dl.content == VALID_TINY_PNG

    # Admin rejection requires rejection_reason; approval passes VerificationCheck.
    missing_reason = await client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers=admin_headers,
        json={"review_status": "REJECTED"},
    )
    assert missing_reason.status_code == 422

    approve_res = await client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers=admin_headers,
        json={"review_status": "APPROVED"},
    )
    assert approve_res.status_code == 200, approve_res.text
    assert approve_res.json()["review_status"] == "APPROVED"

    async with session_factory() as s:
        chk = await s.scalar(
            select(VerificationCheck).where(
                VerificationCheck.branch_id == uuid.UUID(branch_id),
                VerificationCheck.check_type == "LOCAL_LICENSE",
            )
        )
        assert chk is not None
        assert chk.status == "PASSED"


@pytest.mark.asyncio
async def test_hygiene_inspection_critical_failure_override_and_recovery(
    phase3_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, session_factory, _settings = phase3_client
    owner_headers = await _auth_headers(client, f"+9192{uuid.uuid4().int % 10**8:08d}")
    admin_headers = await _auth_headers(client, "+919000000002")

    tag = uuid.uuid4().hex[:6]
    onboard_res = await client.post(
        "/api/v1/partner/salons",
        headers=owner_headers,
        json={
            "legal_name": f"[DEMO] Safety Test Legal {tag}",
            "brand_name": f"[DEMO] Safety Test Salon {tag}",
            "branch_name": f"[DEMO] Koramangala {tag}",
            "address_line1": "21 80ft Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560034",
            "lat": 12.9352,
            "lng": 77.6245,
        },
    )
    assert onboard_res.status_code == 201
    branch_id = onboard_res.json()["branch"]["id"]

    # Featured placement without disclosure label rejected.
    bad_feat = await client.patch(
        f"/api/v1/admin/branches/{branch_id}/governance",
        headers=admin_headers,
        json={"status": "ACTIVE", "is_featured": True},
    )
    assert bad_feat.status_code == 422
    assert bad_feat.json()["error"]["code"] == "FEATURED_DISCLOSURE_REQUIRED"

    # Manual CHAIR_VERIFIED blocked before passing physical hygiene inspection.
    early_verify = await client.patch(
        f"/api/v1/admin/branches/{branch_id}/governance",
        headers=admin_headers,
        json={"verification_status": "CHAIR_VERIFIED"},
    )
    assert early_verify.status_code == 409

    # Activate branch so it is initially discoverable before critical failure.
    assert (
        await client.patch(
            f"/api/v1/admin/branches/{branch_id}/governance",
            headers=admin_headers,
            json={
                "status": "ACTIVE",
                "is_featured": True,
                "featured_disclosure_label": "Sponsored [DEMO]",
            },
        )
    ).status_code == 200

    listed_before = await client.get("/api/v1/branches", params={"q": tag})
    assert listed_before.status_code == 200
    assert any(item["id"] == branch_id for item in listed_before.json()["items"])

    # Score 98 with single_use_blades_ok=False MUST force FAILED_CRITICAL + SUSPENDED.
    fail_insp = await client.post(
        f"/api/v1/admin/branches/{branch_id}/inspections",
        headers=admin_headers,
        json={
            "numerical_score": 98,
            "single_use_blades_ok": False,
            "sharps_disposal_ok": True,
            "instrument_disinfection_ok": True,
            "fresh_towels_ok": True,
            "corrective_action_notes": "Reused blade pack found at Station 1.",
        },
    )
    assert fail_insp.status_code == 201, fail_insp.text
    fail_data = fail_insp.json()
    assert fail_data["inspection"]["overall_outcome"] == "FAILED_CRITICAL"
    assert fail_data["failed_critical_checks"] == ["single_use_blades_ok"]
    assert fail_data["branch_status"] == "SUSPENDED"
    assert fail_data["verification_status"] == "SUSPENDED"

    # Whitespace-only onboarding payload rejected with 422.
    blank_res = await client.post(
        "/api/v1/partner/salons",
        headers=owner_headers,
        json={
            "legal_name": "   ",
            "brand_name": f"[DEMO] Safety Test Salon {tag}",
            "branch_name": f"[DEMO] Blank Legal {tag}",
            "address_line1": "21 80ft Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560034",
            "lat": 12.9352,
            "lng": 77.6245,
        },
    )
    assert blank_res.status_code == 422

    # Suspended branch is hidden from public discovery immediately.
    listed_after_fail = await client.get("/api/v1/branches", params={"q": tag})
    assert listed_after_fail.status_code == 200
    assert not any(item["id"] == branch_id for item in listed_after_fail.json()["items"])

    # Manual badge or activation override blocked until re-inspection passes.
    bypass_res = await client.patch(
        f"/api/v1/admin/branches/{branch_id}/governance",
        headers=admin_headers,
        json={"verification_status": "CHAIR_VERIFIED"},
    )
    assert bypass_res.status_code == 409

    bypass_pending_res = await client.patch(
        f"/api/v1/admin/branches/{branch_id}/governance",
        headers=admin_headers,
        json={"status": "ACTIVE", "verification_status": "PENDING"},
    )
    assert bypass_pending_res.status_code == 409
    assert bypass_pending_res.json()["error"]["code"] == "FAILED_CRITICAL_REINSPECTION_REQUIRED"

    # A SCHEDULED inspection row (completed_at=None) must NOT shadow FAILED_CRITICAL.
    async with session_factory() as s:
        admin_id = uuid.UUID(
            (await client.get("/api/v1/users/me", headers=admin_headers)).json()["id"]
        )
        s.add(
            Inspection(
                branch_id=uuid.UUID(branch_id),
                inspector_user_id=admin_id,
                scheduled_at=datetime.now(),
                completed_at=None,
                numerical_score=0,
                overall_outcome="SCHEDULED",
            )
        )
        await s.commit()

    bypass_after_sched = await client.patch(
        f"/api/v1/admin/branches/{branch_id}/governance",
        headers=admin_headers,
        json={"status": "ACTIVE", "verification_status": "PENDING"},
    )
    assert bypass_after_sched.status_code == 409

    # Branch-scoped PARTNER_STAFF cannot upload KYC docs or view salon-wide owner docs.
    staff_phone = f"+9191{uuid.uuid4().int % 10**8:08d}"
    staff_headers = await _auth_headers(client, staff_phone)
    staff_uid = uuid.UUID(
        (await client.get("/api/v1/users/me", headers=staff_headers)).json()["id"]
    )
    salon_uuid = uuid.UUID(onboard_res.json()["salon"]["id"])
    branch_uuid = uuid.UUID(branch_id)
    async with session_factory() as s:
        s.add(
            UserRoleAssignment(
                user_id=staff_uid,
                role="PARTNER_STAFF",
                salon_id=salon_uuid,
                branch_id=branch_uuid,
            )
        )
        s.add(
            SalonDocument(
                salon_id=salon_uuid,
                branch_id=None,
                document_type="OWNER_ID",
                storage_key=f"kyc/{salon_uuid}/owner-only.png",
                mime_type="image/png",
                size_bytes=len(VALID_TINY_PNG),
                sha256_hex="0" * 64,
                review_status="PENDING",
            )
        )
        await s.commit()

    staff_setup = await client.get(
        f"/api/v1/partner/branches/{branch_id}/setup", headers=staff_headers
    )
    assert staff_setup.status_code == 200
    assert all(d["branch_id"] is not None for d in staff_setup.json()["documents"])

    staff_upload = await client.post(
        f"/api/v1/partner/branches/{branch_id}/documents",
        headers=staff_headers,
        json={
            "document_type": "OWNER_ID",
            "mime_type": "image/png",
            "content_base64": base64.b64encode(VALID_TINY_PNG).decode("ascii"),
        },
    )
    assert staff_upload.status_code == 403

    # Passing re-inspection restores CHAIR_VERIFIED + ACTIVE.
    pass_insp = await client.post(
        f"/api/v1/admin/branches/{branch_id}/inspections",
        headers=admin_headers,
        json={
            "numerical_score": 92,
            "single_use_blades_ok": True,
            "sharps_disposal_ok": True,
            "instrument_disinfection_ok": True,
            "fresh_towels_ok": True,
            "corrective_action_notes": "Verified single-use blade dispenser sealed.",
        },
    )
    assert pass_insp.status_code == 201, pass_insp.text
    assert pass_insp.json()["inspection"]["overall_outcome"] == "PASSED"
    assert pass_insp.json()["verification_status"] == "CHAIR_VERIFIED"
    assert pass_insp.json()["branch_status"] == "ACTIVE"

    listed_verified = await client.get(
        "/api/v1/branches", params={"q": tag, "verified_only": "true"}
    )
    assert listed_verified.status_code == 200
    matched = [item for item in listed_verified.json()["items"] if item["id"] == branch_id]
    assert len(matched) == 1
    assert matched[0]["verification_status"] == "CHAIR_VERIFIED"
    assert matched[0]["featured_disclosure_label"] == "Sponsored [DEMO]"

    async with session_factory() as s:
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.branch_id == uuid.UUID(branch_id),
                AuditLog.action == "HYGIENE_INSPECTION_RECORDED",
            )
        )
        assert audit is not None
