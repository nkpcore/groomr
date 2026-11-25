# Phase 4 (Mobile-First Sequence) — Booking Engine, Holds, Checkout, Walk-Ins & OTP Plan

> **Status:** Active Execution Plan (`docs/plans/roadmap.md`)
> **Scope:** Authoritative 5-minute `slot_holds` backed by PostgreSQL `btree_gist` `EXCLUDE` constraints, atomic `booking_allocations`, `booking_items` pricing/duration snapshots, strict server-side `BookingStatus` state machine + check-in/completion OTPs, decoupled `PAY_AT_SALON` + `TEST_MODE` Razorpay payment orders & signed idempotent webhooks (including late-payment expired-hold auto-refunds), commission ledger accrual on `COMPLETED` platform bookings, partner live walk-in queue + pause endpoints, and `apps/mobile` Hold Countdown/Checkout & `Bookings` tab. Partner onboarding & KYC/Inspection PWA follows immediately in Phase 3/6.

## 1. Schema & Migration (`20261125_0002`)
- Add nullable `bookings.slot_hold_id` FK (`-> slot_holds.id ON DELETE SET NULL`, indexed) so `HELD` and converted `CONFIRMED` bookings link deterministically to their `SlotHold`.
- Keep all money fields in integer `paise` (`INR`) and all timestamps in UTC `TIMESTAMPTZ`.

## 2. Core Invariants
- **No Redis-only locks:** Holds & allocations commit inside ACID PostgreSQL transactions guarded by `uq_active_staff_hold` / `uq_active_resource_hold` and `uq_active_staff_allocation` / `uq_active_resource_allocation` (`btree_gist`).
- **Savepoint fallback for "Any Barber" & chair pooling:** When holding an open multi-staff/multi-chair slot, candidate `(staff_id, resource_id)` pairs are attempted inside SQLAlchemy `begin_nested()` savepoints so concurrent callers distribute safely across available barbers/chairs until zero capacity remains (`409 SLOT_NO_LONGER_AVAILABLE`).
- **Strict Idempotency:** Mutating endpoints (`POST /holds`, `POST /bookings/{id}/confirm-pay-at-salon`, `POST /bookings/{id}/payment-order`, `POST /bookings/{id}/test-payment-capture`, `POST /bookings/{id}/cancel`, `POST /payments/webhook/{provider}`) enforce `Idempotency-Key` (`idempotency_keys` table) or unique `(provider, provider_event_id)` (`payment_events`).
- **Payment Decoupling & Late Webhook Protection:** `Payment.status` never directly overwrites invalid `BookingStatus`. If a `payment.captured` webhook settles after hold expiry and capacity is unavailable, no double booking is permitted—the handler records a `Refund(reason='LATE_PAYMENT_HOLD_EXPIRED', status='PROCESSED')` and `AuditLog` entry.
- **OTP & Commission Integrity:** 6-digit check-in & completion OTPs are hashed with `SECRET_KEY` on `bookings`, revealed only to the authenticated owning customer on `GET /bookings/{id}` / `GET /bookings`, and required constant-time verification when partner/staff move `CONFIRMED -> CHECKED_IN -> IN_SERVICE -> COMPLETED`. Platform commission (`commission_ledger`) accrues strictly once on `COMPLETED` `PLATFORM` bookings.
