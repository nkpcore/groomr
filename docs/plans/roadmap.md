# CHAIR — Product & Engineering Roadmap

Each phase is a self-contained vertical slice gated by migrations, lint, typechecks, and automated unit/integration tests before moving forward.

| Phase | Name | Primary Deliverables | Exit Gate |
| --- | --- | --- | --- |
| **0** | **Foundation** | Monorepo (`apps/api`, `apps/mobile`, `apps/web`, `packages/shared-types`), `docker-compose.yml`, `.env.example`, all 33+ SQLAlchemy/GeoAlchemy2 models + initial Alembic migration (`btree_gist` + PostGIS), `/api/v1/health`, `[DEMO]` seed script, domain invariants (`booking_states`, `hygiene`), unit + concurrency test scaffolding | `ruff`, `mypy`, `pytest` unit/schema tests pass; workspace `typecheck`/`lint` pass; live `alembic upgrade head` & concurrency DB tests pass once Postgres+PostGIS is connected |
| **1** | **Auth, RBAC & Consents** | Phone OTP adapters, JWT access/refresh tokens, RBAC & branch tenant guards, DPDP `user_consents` endpoints, Customer & Partner auth UI | Auth/RBAC integration tests & Playwright login flow pass |
| **2** | **Partner Onboarding & Shop Setup** | Salon/branch CRUD + PostGIS coordinates, private signed KYC uploads, `branch_services`, `staff`, `staff_services`, `staff_shifts`, `schedule_blocks`, `resources` (chairs) | Partner setup API tests, tenant isolation IDOR tests, PWA forms pass |
| **3** | **Customer Discovery & Availability** | PostGIS radius search, filters (distance, price, rating, open now, real availability), featured disclosure, multi-service slot calculator | Availability unit/property tests (shifts, breaks, buffers, walk-ins, pause switch) pass |
| **4** | **Booking Engine, Walk-Ins & OTP** | 5-min `slot_holds`, transactional `booking_allocations`, state machine transitions, check-in/completion OTPs, live walk-in queue, pause toggle | **Multi-coroutine/multi-connection concurrency test proves 0 double-bookings** |
| **5** | **Payments, Ledger & Notifications** | Pay-at-salon + Razorpay test-mode adapter, signature-verified idempotent webhooks, late-payment auto-refund protection, commission ledger, subscriptions, FCM/SMS/email adapters | Webhook replay, expired-hold refund, and commission accrual tests pass |
| **6** | **Trust, Inspections, Style Passport & Polish** | Physical hygiene checklist with critical failure override, admin verification/suspension/disputes/audit UI, completed-only reviews, private Style Passport photos, Hindi `hi` parity, full E2E + budget-Android perf/a11y audit | Full Playwright E2E + Android emulator/RN Web responsive & accessibility audit pass |
