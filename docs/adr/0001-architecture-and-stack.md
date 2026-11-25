# ADR-0001: CHAIR System Architecture, Stack & Boundaries

- **Status:** Proposed (Pre-Coding Baseline)
- **Date:** 2026-11-25
- **Scope:** Entire CHAIR monorepo (`apps/api`, `apps/mobile`, `apps/web`, `packages/shared-types`)

---

## 1. Context

CHAIR requires three coordinated product surfaces—Customer mobile-first app, Partner PWA (`CHAIR Business`), and Admin Operations Console—backed by an ACID-safe hyperlocal booking engine in India that prevents double-booking across barbers, chairs, walk-ins, and expiring payment holds.

Inspection of `c:\Users\nikhil\Desktop\groomr` confirmed a greenfield workspace with `git`, `node v24.19.0`, `npm 12.2.1`, `python 3.14.7`, `uv 0.12.22`, `java 17`, and the Android SDK installed, while `pnpm`, `yarn`, `poetry`, `docker`, `psql`, and `redis-server` are absent on the host.

---

## 2. Decisions

### D1: Monorepo Package Management (`npm workspaces` + `uv`)
- Use **npm workspaces** (`package.json`) for TypeScript packages (`apps/mobile`, `apps/web`, `packages/shared-types`) and **`uv`** for Python (`apps/api`), matching tools already present on the host without requiring `pnpm`/`poetry`.

### D2: Customer App (`apps/mobile` — React Native + Expo Router + RN Web)
- Because the repo is greenfield and Node 24 + Android SDK exist, build the customer app on **Expo (SDK managed workflow) + Expo Router + TypeScript**, using platform-adaptive Material 3 (Android) and HIG (iOS) conventions plus React Native Web export for browser testing.
- Use `FlashList` for salon/service lists, `TanStack Query` with `AsyncStorage` persistence for budget-Android network resilience, `expo-secure-store` for tokens, and `i18next` (`en`/`hi`) for bilingual copy.

### D3: Partner PWA & Admin Console (`apps/web` — Next.js App Router + Tailwind CSS)
- Serve **CHAIR Business** (`/(partner)`) as a high-contrast, installable PWA and **Admin** (`/(admin)`) as a dense, role-gated operational workspace inside a single Next.js TypeScript codebase consuming `@chair/shared-types` and versioned `/api/v1` endpoints.

### D4: Authoritative Backend & Database (`FastAPI` + `PostgreSQL 16` + `PostGIS` + `Redis` + `Celery`)
- **Single source of booking truth:** PostgreSQL + PostGIS (`Geography(Point, 4326)`) + `btree_gist` exclusion constraints on `booking_allocations` and `slot_holds`.
- **Redis** accelerates hot read caching, rate limiting, and Celery queues, **never** replacing PostgreSQL transactional exclusion guarantees.
- **Money & timestamps:** Integer **paise** (`INR`) everywhere; UTC `TIMESTAMPTZ` everywhere.
- **Immutability:** `booking_items` snapshots booked service title, price, duration, and buffers.

### D5: External Provider Adapters
- Every external dependency sits behind an explicit interface in `apps/api/src/chair_api/adapters/`:
  - `OTPProvider`: `MockOTPProvider` (non-prod only) | `SupabaseAuthAdapter` | `FirebaseAuthAdapter` | `MSG91Adapter`
  - `PaymentProvider`: `TestModePaymentAdapter` | `RazorpayAdapter` (HMAC-SHA256 webhook verification + idempotency)
  - `StorageProvider`: `LocalSignedStorageAdapter` | `S3StorageAdapter` | `SupabaseStorageAdapter` (private buckets + signed URLs)
  - `MapsProvider`: PostGIS core + `LocalStubMapsAdapter` | `GoogleMapsAdapter` | `MapboxAdapter`
  - `NotificationProvider`: `ConsoleOutboxAdapter` | `FCMNotificationAdapter` + Email/SMS adapters

### D6: Local Runtime Deviation Note
- Because Docker/PostgreSQL/Redis are not currently installed on the Windows host, Phase 0 provides a canonical `docker-compose.yml` (`postgis/postgis:16-3.4` + `redis:7-alpine`) and full Alembic SQL migrations while allowing unit/API schema tests to run offline and guarding DB integration/concurrency tests on `TEST_DATABASE_URL` availability.

---

## 3. Consequences

- **Positive:** Zero chance of overlapping staff/chair bookings at the DB layer; clean iOS/Android packaging path via Expo EAS; clean decoupling from external Indian vendors until credentials are supplied.
- **Trade-off:** Live PostGIS migration and multi-connection concurrency tests require starting Docker Desktop / local Postgres or connecting a remote PostGIS database.
