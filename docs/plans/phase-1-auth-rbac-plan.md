# Phase 1 — Auth, RBAC, Tenant Isolation & DPDP Consents Plan

> **Status:** Active Execution Plan (`docs/plans/roadmap.md` — Phase 1)
> **Scope Boundary:** Phone OTP authentication, JWT access + refresh rotation, RBAC (`CUSTOMER`, `PARTNER_OWNER`, `PARTNER_STAFF`, `ADMIN`), branch/salon tenant isolation, DPDP consents, audit logging, and Customer/Partner/Admin auth + consent UI. Do not build Phase 2–6 domain screens yet.

## 1. Architecture & Compatibility Summary
- **Database Schema Impact:** **Zero breaking migrations.** Reuses existing Phase 0 tables (`users`, `user_roles`, `user_consents`, `salons`, `branches`, `audit_logs`). Fixes `demo_seed.py` to populate `salon_id` explicitly on the `[DEMO]` owner's `user_roles` row while remaining backwards-compatible with existing seeded DBs.
- **Session & Connection Lifecycle:** Upgrade `apps/api/src/chair_api/main.py` and `db/session.py` to manage shared SQLAlchemy `AsyncEngine` + `async_sessionmaker` and `redis.asyncio.Redis` pools inside FastAPI `lifespan`, eliminating per-request engine creation.
- **OTP & Auth State Store (`AuthStore`):**
  - Challenges, resend/attempt counters, rate limits, and refresh-token families live in Redis with bounded TTLs and atomic scripts/pipelines (`chair:auth:*`).
  - `OTPProvider` stays behind `chair_api/adapters/base.py` (`MockOTPProvider` fixed code `123456` permitted only when `app_env != "production"`, enforced by `Settings.validate_production_safety`).
- **Rollback Plan:** No destructive schema migrations are performed. Any Phase 1 regression can be rolled back cleanly at the application router/dependency layer without database downtime.

## 2. Security Implications & Controls
- **JWT Hardening (`PyJWT` `HS256`):** Strict claim verification (`iss="chair-api"`, `aud="chair-clients"`, `exp`, `iat`, `sub`, `typ`, `jti`), explicit algorithm allowlist (`algorithms=["HS256"]`).
- **Refresh Token Rotation & Replay Detection:** Refresh tokens bind to `(family_id, jti)` with SHA-256 hash stored in Redis. Any replay of a previously rotated `jti` immediately revokes the entire token family, logs `AUTH_REFRESH_REUSE_DETECTED` in `audit_logs`, and returns `401`.
- **Rate Limiting & Brute-Force Protection:** Per-phone (`5 / 15m`) and per-IP (`20 / 15m`) OTP request limits, plus max `5` verification attempts per challenge before invalidating the challenge and returning `429`.
- **Fresh Server-Side Authorization:** `get_current_principal` resolves `User` (`is_active=True`) and `UserRoleAssignment` rows from PostgreSQL on every request so deactivated accounts and revoked roles take effect immediately.
- **Tenant & IDOR Prevention:** `assert_salon_access` and `assert_branch_access` verify explicit `(role, salon_id, branch_id)` ownership before returning tenant data; unauthorized cross-tenant probes return `403`.
- **DPDP & Privacy:** `UserConsent` stores append-only decision history for `TERMS`, `PRIVACY_DPDP`, `MARKETING`, `LOCATION`, and `STYLE_PASSPORT_PHOTOS`, storing HMAC-SHA256 `ip_hash` (never raw IP) + truncated `user_agent` and writing pseudonymized `audit_logs`.
- **Web Token Storage Trade-off (Phase 1 Dev/CORS):** While Next.js Web (`localhost:3000`) and FastAPI (`localhost:8000`) run cross-origin in local development, web refresh/access tokens persist via `window.localStorage` (`chair.auth.session.v1`); before production deployment under a shared domain or gateway proxy, move web refresh tokens to `HttpOnly; Secure; SameSite=Lax` cookies.

## 3. API Contract (`/api/v1`)
1. `POST /api/v1/auth/otp/request` — Request E.164 phone OTP challenge.
2. `POST /api/v1/auth/otp/verify` — Verify OTP -> issue access + refresh JWT pair, auto-provision `CUSTOMER` role for first-time users, record `USER_LOGIN` audit entry.
3. `POST /api/v1/auth/refresh` — Rotate refresh token -> issue fresh access + refresh pair (revoking entire family on replay).
4. `POST /api/v1/auth/logout` — Revoke refresh token family and log `USER_LOGOUT`.
5. `GET /api/v1/users/me` — Profile, roles, and effective DPDP consent state.
6. `PATCH /api/v1/users/me` — Update `full_name`, `email`, and `preferred_locale` (`en` | `hi`) + audit entry.
7. `GET /api/v1/users/me/consents` — Effective DPDP consent map + chronological history.
8. `PUT /api/v1/users/me/consents` — Grant/revoke consent decisions + audit entry.
9. `GET /api/v1/partner/context` & `GET /api/v1/partner/branches/{branch_id}/access` — `PARTNER_OWNER` / `PARTNER_STAFF` tenant-isolated scope endpoints.
10. `GET /api/v1/admin/audit-logs` — `ADMIN`-only recent audit trail viewer.

## 4. Frontend & Mobile UI Plan
- **Shared Types & i18n (`packages/shared-types`):** Add typed Auth/User/Consent/Partner/Admin DTOs and complete `en.json` + `hi.json` copy parity.
- **Web (`apps/web`):** Upgrade Customer (`/`), Partner (`/partner`), and Admin (`/admin`) surfaces with:
  - Single-field `<input type="tel">` and single-field `<input type="text" inputmode="numeric" autocomplete="one-time-code">` OTP forms + WebOTP (`AbortController`) + blur validation & accessible error states.
  - Profile + DPDP consent form inside semantic `<fieldset>` + `<legend>`.
  - Explicit `loading`, `empty`, `error`, `offline`, and `permission-denied` UI states, Warm Ivory / Charcoal / Olive / Bronze tokens, no eyebrows above headings.
- **Mobile (`apps/mobile`):** `SecureStore` (native) / Web session storage wrapper, React Query auth context, OTP sign-in + Profile + DPDP consent UI with `>= 48dp` targets and EN/HI support.

## 5. Verification Strategy (TDD)
- **Backend Unit Tests:** JWT signature/alg-confusion/expiry rejection, OTP mock/brute-force/rate-limit rules, refresh-token reuse revocation, RBAC & tenant branch/salon IDOR denial.
- **Backend Integration Tests (Live Docker PostGIS + Redis):** Full HTTP flow across `otp/request` -> `otp/verify` -> `refresh` -> `logout`, `users/me/consents` DB persistence + `audit_logs` rows, and multi-tenant isolation across seeded `[DEMO]` owner/customer/admin users.
- **Frontend & E2E Tests:** Shared dictionary key-parity & typecheck, Vitest component/API helper tests, `next build`, `impeccable detect`, and live Playwright E2E verifying OTP login, DPDP consent save, EN/HI switching, and `403 permission-denied` handling across `/`, `/partner`, and `/admin`.
