# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Stack

React Native + Expo (`expo-router`, TypeScript, React Native Web) for Customer App (`apps/mobile`); Next.js + TypeScript + Tailwind CSS for Partner PWA and Admin Console (`apps/web`); Python FastAPI + PostgreSQL/PostGIS + Redis + Celery for Backend API and booking engine (`apps/api`); `@chair/shared-types` for shared contracts and `en`/`hi` dictionaries. *(Live PostgreSQL+PostGIS and Redis container runtime pending Docker Desktop or remote URI configuration on host.)*

## Users

- **Customers (Men across Indian urban/metro neighborhoods):** Seeking trustworthy, nearby barbershops and stylists with real-time slot availability, transparent pricing/duration, and reliable check-in—often on budget Android phones and intermittent cellular networks.
- **Salon Partners & Stylists (`CHAIR Business`):** Barbershop owners, branch managers, and stylists juggling walk-ins, chair capacity, shifts, online bookings, and daily payouts/earnings during busy shop hours.
- **Marketplace Administrators & Inspectors:** Internal operations and trust teams verifying business KYC, executing physical hygiene inspections, resolving disputes/refunds, and tuning commissions/subscriptions.

## Product Purpose

CHAIR is a hybrid hyperlocal men's grooming marketplace and SaaS operations platform in India. It lets customers discover nearby verified barbershops, compare services, prices, stylists, and genuine real-time availability, and book seamlessly; it equips salons to run walk-ins, chairs, staff shifts, appointments, and earnings from a single fast console.

## Positioning

Unlike static salon directories or listing sites with fake slots, CHAIR enforces **PostgreSQL-backed chair + stylist + shift + hold concurrency** so displayed slots reflect real shop capacity across both online bookings and live walk-ins, paired with **CHAIR VERIFIED**—an independent platform physical & hygiene inspection program with mandatory critical safety checks.

## Operating Context

- Hyperlocal discovery via PostGIS geospatial radius/zones (`DEFAULT_SEARCH_RADIUS_METERS=5000`) with manual location fallback.
- Hybrid fulfillment: scheduled online appointments (`HELD` -> `CONFIRMED` -> `CHECKED_IN` -> `IN_SERVICE` -> `COMPLETED`) alongside live in-shop `walk_ins` sharing the same barbers and chairs.
- Pay-at-salon supported at launch; online payments (UPI/cards), SMS OTP, maps, object storage, and push alerts mediated through swappable adapters.
- Bilingual product copy architecture supporting English (`en`) and Hindi (`hi`).

## Capabilities and Constraints

- **Authoritative booking truth:** PostgreSQL + PostGIS + `btree_gist` exclusion constraints; 5-minute configurable hold expiry; server-enforced state machine.
- **Commercial experiments (admin-configurable, never hardcoded):** Starter (`₹0/branch/month`, `8%` commission), Pro (`₹499/branch/month`, `6%` commission), Growth (`₹999/branch/month`, `4%` commission), applied only to eligible `COMPLETED` platform-originated bookings.
- **Trust & safety:** Mandatory critical hygiene checks (single-use razor blades, safe sharps disposal, disinfected reusable instruments, fresh towels) override numerical inspection scores.
- **Undecided / pending confirmation:** Local vs. cloud PostgreSQL+PostGIS runtime for dev tests; third-party sandbox credentials (Razorpay, MSG91/Supabase/Firebase, S3, Google Maps/Mapbox).

## Brand Commitments

- **Brand Name:** `CHAIR` (Customer), `CHAIR Business` (Partner PWA).
- **Explicit Visual Brief:** Warm ivory, charcoal, muted olive, subtle bronze accents, editorial photography, generous spacing, refined typography, restrained motion. Reject generic SaaS gradients, neon accents, and excessive glassmorphism.
- **Badge Terminology:** `CHAIR VERIFIED` must always clarify it is an independent platform verification badge, not government certification. Featured placements must carry clear disclosure.

## Evidence on Hand

- Greenfield workspace initialized with governance rules, ADR, 33+ entity schema specification, and phased execution plans; zero production customer data, ratings, or live merchant integrations exist yet.
- Seed fixtures created in Phase 0 will be explicitly labeled `[DEMO]` and must never be represented as live barbershops or real customer reviews.

## Product Principles

1. **Real capacity over optimistic promises:** Never show or sell a slot that conflicts with a barber's shift, break, chair, hold, or walk-in.
2. **Trust earned through verification & transparency:** Prices, durations, hygiene safety outcomes, and sponsored placements are unambiguous.
3. **Calm craft for customers, speed for barbers:** Customer flows feel unhurried and editorial; partner tools optimize for one-handed speed between haircuts.
4. **Privacy by design for personal style & KYC:** Private customer Style Passport photos and partner documents stay behind strict consent and signed-URL boundaries.

## Accessibility & Inclusion

- Minimum `48dp` (`44pt` iOS) touch targets, WCAG AA contrast across light/warm-ivory and partner high-contrast views, screen-reader semantics, and English/Hindi localization support.
- Resilient loading, empty, error, offline, and permission-denied states engineered for budget Android devices and flaky networks.
