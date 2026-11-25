# CHAIR — Compliance, Security & Missing Integrations Checklist

> **Disclaimer:** Technical architecture controls are implemented in code; items marked **[CA / Legal Review Required]** must be reviewed by qualified Indian Chartered Accountants and legal counsel before public launch.

---

## 1. Missing Secrets & Third-Party Integrations

None of these credentials exist in the workspace yet. All integrations must remain in **test/stub mode** with placeholders in `.env.example` until provisioned:

| Category | Env Keys | Current State | Launch Prerequisite |
| --- | --- | --- | --- |
| Database / Cache | `DATABASE_URL`, `TEST_DATABASE_URL`, `REDIS_URL` | Missing local engine | Start Docker `docker-compose.yml` or provide PostGIS 16 + Redis 7 URI |
| Phone OTP | `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID`, `SUPABASE_*`, `FIREBASE_PROJECT_ID` | Missing (`mock` dev adapter only) | Register TRAI DLT entity/template IDs before sending live Indian SMS OTP |
| Payments | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Missing (`test_mode` adapter only) | Merchant KYC approval & webhook secret configuration |
| Private Object Storage | `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Missing (`local_signed` dev adapter only) | Private S3/Supabase bucket with CORS & lifecycle rules |
| Maps & Geocoding | `GOOGLE_MAPS_API_KEY`, `MAPBOX_ACCESS_TOKEN` | Missing (`local_stub` + PostGIS) | Billing-enabled API key with domain/app restrictions |
| Push & Email | `FCM_CREDENTIALS_JSON`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` | Missing (`console_outbox` adapter) | Firebase service account & SPF/DKIM-verified SMTP domain |

---

## 2. India Privacy, Trust & Commercial Safeguards

### Digital Personal Data Protection (DPDP) & Privacy **[CA / Legal Review Required]**
- Capture explicit granular consents (`user_consents`) for Terms, Marketing, Location, and **Style Passport photo storage**.
- Store `style_photos` and partner `salon_documents` in private buckets; enforce MIME/magic-byte verification, max size (`5 MB`), and time-limited signed URLs on authorized endpoints only.
- Provide customer account/photo deletion & consent withdrawal workflows with documented retention windows.

### Payments, GST & Marketplace Settlements **[CA / Legal Review Required]**
- Store all ledger entries (`payments`, `refunds`, `settlements`, `commission_ledger`, `subscription_invoices`) in integer **paise** (`INR`).
- Keep `bookings.status` strictly decoupled from `payments.status`; verify payment webhook HMAC signatures and store `provider_event_id` idempotently.
- **Review items before collecting online payments for third-party salons:**
  1. RBI Payment Aggregator / Nodal-Escrow rules when collecting on behalf of salons vs. direct Razorpay Route/Marketplace splits.
  2. GST applicability on platform SaaS subscriptions (`₹499`, `₹999`), commission invoices (`8%`/`6%`/`4%`), and e-commerce TCS under Section 52 of the CGST Act.
  3. Consumer Protection (E-Commerce) Rules, 2020 disclosures (merchant details, transparent cancellation/refund policy, grievance officer contact).

### Trust, Verification & Hygiene Integrity
- **`CHAIR VERIFIED` Labeling:** UI and API copy must explicitly state `CHAIR VERIFIED` is an independent platform verification badge, **not** government certification or statutory licensing.
- **Mandatory Critical Safety Override:** During `inspections`, failing any of the 4 critical items (`single_use_blades_ok`, `sharps_disposal_ok`, `instrument_disinfection_ok`, `fresh_towels_ok`) must force `overall_outcome = 'FAILED_CRITICAL'` regardless of score, blocking/suspending verification and logging an `audit_logs` entry.
- **Featured Disclosures:** Promoted/featured branch placements must carry explicit `is_featured` metadata and visible `"Featured"` / `"Sponsored"` labels.
- **Local Licensing:** Track municipal trade licenses / Shops & Establishments registration in `salon_documents` where applicable per state/municipality.
