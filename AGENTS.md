# CHAIR — Repository Engineering & Agent Governance

> Canonical repository rules for human engineers and AI coding agents working in `groomr`.

## 1. Source-of-Truth Documents
Read these before modifying architecture, schemas, or UI:
1. [PRODUCT.md](PRODUCT.md) — Confirmed product scope, audiences, constraints, and platform direction.
2. [docs/adr/0001-architecture-and-stack.md](docs/adr/0001-architecture-and-stack.md) — Monorepo, stack, adapters, and deviation notes.
3. [docs/architecture/database-schema.md](docs/architecture/database-schema.md) — Authoritative 33-entity schema, PostGIS, and exclusion constraints.
4. [docs/plans/roadmap.md](docs/plans/roadmap.md) & [docs/plans/phase-0-foundation-plan.md](docs/plans/phase-0-foundation-plan.md) — Phased execution and TDD checkpoints.
5. [docs/compliance-checklist.md](docs/compliance-checklist.md) — Privacy, hygiene safety, GST/RBI review flags, and missing secrets.

## 2. Non-Negotiable Execution Rules
- **Inspect before editing:** Read existing code, dependencies, and tests before modifying any module. Never rewrite working code wholesale.
- **Work one vertical phase at a time:** Follow the active phase plan. Do not prematurely scaffold unapproved future screens.
- **No fabricated functionality:** Every visible control must work. Never fake availability, ratings, payment success, or passing integrations.
- **Demo labeling:** Seed/sample fixtures must be clearly marked as demo data (`[DEMO]`).
- **Verify every phase:** Run migrations (when DB available), lint, typechecks, and unit/integration tests after edits; fix regressions before advancing.
- **No accidental secret exposure:** Never commit `.env`, API keys, tokens, or PII; use `.env.example` placeholders only.
- **No public deployment or paid side effects:** Never deploy publicly, provision paid resources, or send live SMS/emails/payments without explicit approval.

## 3. Core Technical Invariants
- **Authoritative booking state:** PostgreSQL + PostGIS + `btree_gist` exclusion constraints are the booking source of truth; Redis is cache/rate-limiting only.
- **Money & time:** Store all monetary values in integer **paise** (`INR`, `100 paise = ₹1`) and all timestamps as UTC `TIMESTAMPTZ`.
- **Historical immutability:** Snapshot booked service name, price, duration, and buffers onto `booking_items`.
- **State machine & authorization:** Enforce `BookingStatus` transitions and tenant/role isolation on the FastAPI backend—never trust frontend status strings.
- **Modular rules:** See `.agents/rules/` for domain-specific backend, booking-engine, frontend, and security rules.
