# Phase 3 (+ Admin Inspections & Verification) — Partner Onboarding, Shop Setup & Hygiene Governance Plan

> **Status:** Active Execution Plan (`docs/plans/roadmap.md`)
> **Scope:** Complete Partner Operations & Onboarding (`POST/PATCH` for salons, PostGIS branches, services, staff/shifts/blocks, chairs, private signed KYC documents, plus live Bookings Desk & Walk-In Queue UI) and Admin Verification & Physical Hygiene Governance (KYC review, signed previews, critical hygiene failure `FAILED_CRITICAL` override, suspension, featured disclosures, audit logs).

## 1. Security & Trust Rules Enforced
- **Private KYC Assets (`salon_documents`):** Stored via `StorageProvider` (`LocalSignedStorageAdapter` in dev/test; S3/Supabase required in staging/prod). Rejects spoofed magic bytes, unsupported MIME types, and files > `MAX_UPLOAD_SIZE_BYTES` (`5 MB`). Served strictly on `GET /api/v1/assets/signed` requiring BOTH valid short-lived HMAC signature (`sig`, `expires`) AND authenticated `AuthPrincipal` authorized for that document (`ADMIN` or owning `PARTNER_OWNER`/`PARTNER_STAFF`).
- **`FAILED_CRITICAL` Safety Override:** Any inspection with `single_use_blades_ok`, `sharps_disposal_ok`, `instrument_disinfection_ok`, or `fresh_towels_ok` set to `False` forces `overall_outcome = 'FAILED_CRITICAL'` via `evaluate_inspection(...)` and suspends branch verification (`verification_status = 'SUSPENDED'`), removing the branch from public discovery.
- **`CHAIR VERIFIED` Disclaimer & Featured Disclosures:** Every verification surface notes platform verification is independent and not government licensing; enabling `is_featured` enforces explicit disclosure labeling.
- **Tenant Isolation:** Every branch/salon endpoint enforces `assert_salon_access` or `assert_branch_access` server-side before returning or mutating rows; onboarding a brand-new salon scopes `PARTNER_OWNER` strictly to that newly created `salon.id`.
