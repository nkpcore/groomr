---
trigger: glob
globs: "**/apps/api/**/*.py"
description: FastAPI, PostgreSQL, PostGIS, and Python backend engineering standards
---

# Backend & Database Standards

- Version every HTTP endpoint under `/api/v1` and validate request/response payloads with Pydantic v2.
- Store money strictly as integer `paise` (`int`) and timestamps in UTC (`datetime.now(timezone.utc)` / `TIMESTAMPTZ`).
- Enforce RBAC (`CUSTOMER`, `PARTNER_OWNER`, `PARTNER_STAFF`, `ADMIN`) and tenant (`salon_id` / `branch_id`) isolation inside dependencies/services, never on the client.
- Keep external providers (OTP, Razorpay, S3/Supabase, Maps, FCM/SMS) behind adapter interfaces in `chair_api/adapters/`.
- Write audit records to `audit_logs` for every verification decision, suspension, refund, rate change, and booking override.

```python
# ✅ GOOD: Integer paise + UTC
price_paise: int = 49900  # ₹499.00
created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ❌ BAD: Float rupees or naive local datetime
price_inr: float = 499.0
created_at = datetime.now()
```
