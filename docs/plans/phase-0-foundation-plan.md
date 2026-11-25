# Phase 0 — Foundation Implementation Plan

> **For agentic execution:** Execute task-by-task following TDD and verification gates. Steps use `- [ ]` checkboxes. Do not build full feature screens prematurely in Phase 0.

**Goal:** Build the runnable monorepo foundation for CHAIR (`apps/api`, `packages/shared-types`, `apps/mobile`, `apps/web`), complete PostgreSQL + PostGIS + `btree_gist` schema & Alembic migration, `/api/v1/health`, `[DEMO]` seed data, and automated unit + concurrency test scaffolding.

**Architecture:** `npm` workspaces manage TypeScript apps (`apps/mobile` Expo Router + RN Web, `apps/web` Next.js App Router + Tailwind, `packages/shared-types`); `uv` manages `apps/api` (FastAPI + SQLAlchemy 2.0 async + GeoAlchemy2 + Alembic + Celery + Pytest). PostgreSQL enforces booking concurrency via `TSTZRANGE` + `btree_gist` exclusion constraints.

**Spec & Governance References:**
- [PRODUCT.md](../../PRODUCT.md)
- [ADR-0001](../adr/0001-architecture-and-stack.md)
- [Database Schema](../architecture/database-schema.md)
- [Compliance Checklist](../compliance-checklist.md)

## Global Constraints
- Store money strictly in integer `paise` (`INR`); timestamps strictly UTC `TIMESTAMPTZ`.
- Prefix all HTTP API routes under `/api/v1`.
- Never commit `.env` or real secrets; keep test/mock adapters safe and disabled in production.
- Label all demo seed rows explicitly with `[DEMO]`.
- Keep frontend Phase 0 surfaces limited to minimal health-connected foundation shells.

---

### Task 1: Monorepo Root & Local Infrastructure Files
**Files:**
- Create: `package.json`
- Create: `docker-compose.yml`
- Create: `docs/mobile-packaging.md`

- [ ] **Step 1:** Author root `package.json` defining workspaces (`packages/*`, `apps/web`, `apps/mobile`) and aggregate scripts (`typecheck`, `lint`, `test`).
- [ ] **Step 2:** Author `docker-compose.yml` with `postgis/postgis:16-3.4` (auto-creating `chair_db` and `chair_test_db`), `redis:7-alpine`, and healthchecks.
- [ ] **Step 3:** Author `docs/mobile-packaging.md` documenting `ANDROID_HOME=C:\Users\nikhil\AppData\Local\Android\Sdk`, `eas.json` profiles, and React Native Web fallback parity.

---

### Task 2: FastAPI Core, Settings, Error Envelope & `/api/v1/health`
**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/chair_api/__init__.py`
- Create: `apps/api/src/chair_api/core/config.py`
- Create: `apps/api/src/chair_api/core/errors.py`
- Create: `apps/api/src/chair_api/core/logging.py`
- Create: `apps/api/src/chair_api/api/v1/health.py`
- Create: `apps/api/src/chair_api/main.py`
- Test: `apps/api/tests/unit/test_health.py`

- [ ] **Step 1 (TDD Red):** Write `tests/unit/test_health.py` testing `GET /api/v1/health` returns `200` (or structured dependency status `ok`/`degraded` with `service="chair-api"`, `version`, `hold_ttl_seconds`, `checks.database`, `checks.redis`), and `GET /openapi.json` exposes `/api/v1/health`.
- [ ] **Step 2:** Run `uv sync --dev` and `uv run pytest tests/unit/test_health.py -v` -> confirm FAIL (module missing).
- [ ] **Step 3 (TDD Green):** Implement `config.py` (Pydantic `BaseSettings` reading `.env.example` keys), `errors.py` (`ChairAPIError` envelope with `code`, `message`, `details`, `request_id`), `health.py`, and `main.py`.
- [ ] **Step 4:** Run `uv run pytest tests/unit/test_health.py -v` -> confirm PASS.

---

### Task 3: Domain Invariants (`enums`, `booking_states`, `hygiene`, Adapter Interfaces)
**Files:**
- Create: `apps/api/src/chair_api/domain/enums.py`
- Create: `apps/api/src/chair_api/domain/booking_states.py`
- Create: `apps/api/src/chair_api/domain/hygiene.py`
- Create: `apps/api/src/chair_api/adapters/base.py`
- Test: `apps/api/tests/unit/test_booking_state_machine.py`
- Test: `apps/api/tests/unit/test_hygiene_override.py`

- [ ] **Step 1 (TDD Red):** Write unit tests for:
  - Every valid and invalid `BookingStatus` transition (including terminal states `COMPLETED`, `CANCELLED`, `EXPIRED`, `NO_SHOW` rejecting further mutations, and role authorization checks).
  - Critical hygiene override: `evaluate_inspection(score=95, single_use_blades_ok=False, ...)` MUST return `FAILED_CRITICAL` regardless of high numerical score.
- [ ] **Step 2:** Run pytest on both test files -> confirm FAIL.
- [ ] **Step 3 (TDD Green):** Implement `enums.py`, `booking_states.py` (`ALLOWED_BOOKING_TRANSITIONS`, `assert_valid_transition`), `hygiene.py` (`evaluate_inspection_outcome`), and `adapters/base.py` (Protocol/ABC definitions + safe test stubs for OTP, Payments, Storage, Maps, Notifications).
- [ ] **Step 4:** Run pytest -> confirm PASS.

---

### Task 4: Complete 33+ Entity SQLAlchemy Models & Initial Alembic Migration
**Files:**
- Create: `apps/api/alembic.ini`
- Create: `apps/api/migrations/env.py`
- Create: `apps/api/src/chair_api/db/base.py`
- Create: `apps/api/src/chair_api/db/session.py`
- Create: `apps/api/src/chair_api/db/models/identity.py` (`users`, `user_roles`, `user_consents`)
- Create: `apps/api/src/chair_api/db/models/marketplace.py` (`service_zones`, `salons`, `branches`, `salon_documents`, `verification_checks`, `inspections`)
- Create: `apps/api/src/chair_api/db/models/catalog.py` (`services`, `branch_services`, `staff`, `staff_services`, `staff_shifts`, `schedule_blocks`, `resources`)
- Create: `apps/api/src/chair_api/db/models/booking.py` (`bookings`, `booking_items`, `booking_allocations`, `slot_holds`, `walk_ins`, `idempotency_keys`)
- Create: `apps/api/src/chair_api/db/models/billing.py` (`subscription_plans`, `payments`, `payment_events`, `refunds`, `settlements`, `commission_ledger`, `subscriptions`, `subscription_invoices`)
- Create: `apps/api/src/chair_api/db/models/trust.py` (`reviews`, `style_profiles`, `style_photos`, `support_cases`, `notifications`, `audit_logs`)
- Create: `apps/api/src/chair_api/db/models/__init__.py`
- Create: `apps/api/migrations/versions/20261125_0001_initial_schema.py`
- Test: `apps/api/tests/unit/test_schema_metadata.py`

- [ ] **Step 1 (TDD Red):** Write `test_schema_metadata.py` asserting `Base.metadata.tables` contains all 33 core entity names + 3 supporting tables, every table uses UUID PKs, monetary columns use integer types (`_paise`), and `booking_allocations` & `slot_holds` define `ExcludeConstraint` constraints (`uq_active_staff_allocation`, `uq_active_resource_allocation`, `uq_active_staff_hold`, `uq_active_resource_hold`).
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_schema_metadata.py -v` -> confirm FAIL.
- [ ] **Step 3 (TDD Green):** Implement all SQLAlchemy 2.0 + GeoAlchemy2 models and write Alembic migration `20261125_0001_initial_schema.py` enabling `pgcrypto`, `postgis`, `btree_gist` and creating all tables, indexes, and exclusion constraints cleanly.
- [ ] **Step 4:** Run `uv run pytest tests/unit/test_schema_metadata.py -v` -> confirm PASS.

---

### Task 5: Celery Skeleton, Demo Seed & Concurrency Integration Test Suite
**Files:**
- Create: `apps/api/src/chair_api/workers/celery_app.py`
- Create: `apps/api/src/chair_api/db/seeds/demo_seed.py`
- Create: `apps/api/tests/integration/conftest.py`
- Create: `apps/api/tests/integration/test_concurrency_booking.py`

- [ ] **Step 1:** Implement Celery app & `expire_stale_slot_holds` task stub (`celery_app.py`).
- [ ] **Step 2:** Implement idempotent `demo_seed.py` seeding `Starter`/`Pro`/`Growth` plans, canonical services, and 2 clearly labeled `[DEMO]` salons/branches (e.g., Indiranagar Bengaluru & Bandra West Mumbai) with staff, shifts, chairs, and sample verified/pending inspection states.
- [ ] **Step 3:** Implement `test_concurrency_booking.py` running `asyncio.gather` across separate DB connections attempting to allocate the same `(staff_id, tstzrange)` and `(resource_id, tstzrange)` simultaneously—asserting exactly 1 succeeds and all concurrent contenders fail with `IntegrityError` (`ExclusionViolation`). Auto-skip cleanly with explicit reason if `TEST_DATABASE_URL` Postgres+PostGIS is unreachable.

---

### Task 6: Shared Types, Next.js Web Shell & Expo Mobile Shell
**Files:**
- Create: `packages/shared-types/` (`package.json`, `tsconfig.json`, `src/index.ts`, `src/i18n/en.json`, `src/i18n/hi.json`, unit test)
- Create: `apps/web/` (Next.js App Router + Tailwind CSS + CHAIR color tokens + `/`, `/partner`, `/admin` health-connected stubs + PWA `manifest.ts` + Vitest & Playwright config)
- Create: `apps/mobile/` (Expo Router + TypeScript + `app.json` + `eas.json` + CHAIR tokens + `en`/`hi` i18n setup + health-connected landing stub + Jest smoke test)

- [ ] **Step 1:** Build `packages/shared-types` (`formatINRFromPaise`, `BookingStatus`, `UserRole`, EN/HI base dictionaries) and unit test it.
- [ ] **Step 2:** Build minimal `apps/web` and `apps/mobile` shells wired to `/api/v1/health` with `loading`/`error`/`offline` feedback.
- [ ] **Step 3:** Run full verification across `apps/api` (`ruff`, `mypy`, `pytest`, OpenAPI export check) and npm workspaces (`npm run typecheck`, `npm run lint`, `npm test`), then report status and ready Phase 1 transition.
