# Phase 2 (Mobile-First) — Customer Discovery, Availability & Mobile App Plan

> **Status:** Active Execution Plan (`docs/plans/roadmap.md` — Reordered Phase 2)
> **Scope Boundary:** Public read-only PostGIS branch discovery, real multi-service slot availability calculation, and `apps/mobile` Customer Explore + Branch Detail + Live Slot Picker + Account tabs backed by seeded `[DEMO]` branches in PostgreSQL. Partner CRUD (`salons`/`services`/`staff`) follows in Phase 3; transactional hold creation & checkout (`slot_holds`, `bookings`) follows in Phase 4.

## 1. Architecture & Compatibility Summary
- **Database Schema Impact:** **Zero breaking migrations.** Reads directly from Phase 0 seeded PostgreSQL + PostGIS tables (`salons`, `branches`, `branch_services`, `services`, `staff`, `staff_services`, `staff_shifts`, `schedule_blocks`, `resources`, `booking_allocations`, `slot_holds`, `walk_ins`, `reviews`, `inspections`).
- **Geospatial & Pricing Rules:**
  - Distance & radius search uses PostGIS `Geography(Point, 4326)` (`ST_DWithin` + `ST_Distance`).
  - All monetary fields remain integer `paise` (`INR`); all timestamps remain UTC `TIMESTAMPTZ` (shift evaluation uses branch `staff_shifts.timezone`, defaulting to `Asia/Kolkata`).
  - Only `branches.status == 'ACTIVE'` and `salons.status == 'ACTIVE'` appear in public discovery.
  - Promoted placements carry explicit `is_featured` and `featured_disclosure_label`; `verification_status == 'CHAIR_VERIFIED'` includes explicit platform verification disclaimer. Unreviewed shops return `avg_rating = None, review_count = 0` cleanly.

## 2. Real Slot Availability Engine (`apps/api/src/chair_api/services/availability.py`)
1. Enforce `online_booking_paused` (returns zero online slots immediately when paused).
2. Resolve branch `operating_hours_json` for requested local weekday in branch timezone (`Asia/Kolkata`).
3. Validate requested `branch_service_ids` belong to the target branch and are active.
4. Resolve candidate `staff` who are `ACTIVE`, `is_accepting_bookings == True`, and hold active `staff_services` for **all** requested `branch_service_ids`.
5. Compute combined service duration (respecting `custom_duration_minutes` overrides) + pre/post buffers (`first.buffer_before_minutes`, `last.buffer_after_minutes`).
6. Subtract `schedule_blocks` (branch-wide and staff-specific), active `booking_allocations`, unexpired active `slot_holds` (`expires_at > now_utc`), active `walk_ins`, and shared `resources` (chair) pool capacity across 15-minute slot intervals after `now_utc + lead_time`.

## 3. REST API Contract (`/api/v1`)
- `GET /api/v1/branches` — Geospatial/city/text/category/price/verified/open-now search & sorting, returning distance, starting price `paise`, featured disclosure, review summary, and next live slot preview.
- `GET /api/v1/branches/{branch_id}` — Full branch details, active localized services, verified/qualified staff list, active chair count, published reviews summary, and latest inspection outcome.
- `GET /api/v1/branches/{branch_id}/availability` — Real computed time slots (`start_at`, `end_at`, `available_staff`, `available_chair_count`) for chosen `branch_service_ids`, `date`, and optional `staff_id`.

## 4. Mobile App Architecture (`apps/mobile` — Expo Router)
- **Shared Navigation & State (`AppStateProvider`):** Unified session, `en`/`hi` locale toggle (synced with profile when signed in), and city/location state (`Bengaluru — Indiranagar`, `Mumbai — Bandra West`, `Current GPS`, or all cities).
- **Bottom Tabs (`src/app/(tabs)/`):**
  - **Explore (`index.tsx`):** Calm Warm Ivory editorial discovery feed using CHAIR tokens, search bar, verified/category/open/price filter pills (`>= 48dp`), `FlatList` / `FlashList`, explicit `loading`, `empty`, `error`, `offline`, and `permission-denied` (location denied fallback!) states.
  - **Account (`account.tsx`):** Preserves Phone OTP sign-in, Profile/Language editor, DPDP Consent toggles, Sign Out, and live API health status.
- **Branch Detail & Live Slot Picker (`src/app/branch/[id].tsx`):**
  - Localized services multi-select, optional barber filter, 7-day IST date selector, real-time slot grid backed by `/availability`, transparent total price (`₹`) + duration summary, and honest slot reservation preview (pointing to Phase 4 booking hold completion — zero fake booking confirmations).

## 5. Verification Strategy
- **Backend Unit Tests:** Exhaustive interval math tests (branch closed, `online_booking_paused`, staff shift bounds, breaks/leaves, multi-service custom duration & buffer overlap, chair pool exhaustion, active hold & walk-in blocking).
- **Backend Integration Tests (Live PostGIS):** `ST_DWithin` radius & distance ordering, active-only branch/salon filtering, rating honesty (`None` on 0 reviews), featured/verified labels, and real DB hold/allocation/block excluding returned slots.
- **Mobile & Expo Web E2E:** `@chair/shared-types` key parity + Vitest mobile service/logic tests, `npm run typecheck`, `npm run lint`, Expo Web export/serve (`390x844` mobile viewport Playwright test checking live API discovery, filters, branch detail multi-service slot selection, and EN/HI switching with zero console/page errors), plus `adb`/Android check notes.
