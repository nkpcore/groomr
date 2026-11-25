---
trigger: glob
globs: "**/apps/api/**/*booking*.py, **/apps/api/**/*hold*.py, **/apps/api/**/*availability*.py, **/apps/api/**/*payment*.py, **/apps/api/**/*walk_in*.py, **/apps/api/**/*allocation*.py"
description: Critical invariants for availability, holds, double-booking prevention, and payment safety
---

# Booking Engine & Concurrency Invariants

- Availability must account for branch hours, `staff_shifts`, `schedule_blocks` (breaks/leaves), `staff_services` qualification, duration + buffers, `resources` (chairs), `booking_allocations`, `walk_ins`, and active `slot_holds`.
- Never rely on Redis alone for slot locking. All hold/booking commits run inside an ACID PostgreSQL transaction backed by `btree_gist` `EXCLUDE` constraints on `(staff_id, allocated_range)` and `(resource_id, allocated_range)`.
- Default `slot_holds` expiry is configurable (`BOOKING_HOLD_TTL_SECONDS`, default `300`s).
- Keep `payments.status` separate from `bookings.status`. Enforce the valid `BookingStatus` transition table strictly on the server.
- If a payment webhook settles after a hold expires, re-check availability inside the DB transaction; if taken, **never double-book**—trigger an automatic `refunds` flow.
- Snapshot `service_name`, `unit_price_paise`, `duration_minutes`, and buffers onto `booking_items` at creation.
- Require `Idempotency-Key` on hold, booking, refund, and webhook handlers; verify provider webhook signatures before processing.
