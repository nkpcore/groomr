---
trigger: always_on
description: Trust, hygiene verification, Indian privacy, and security enforcement rules
---

# Security, Privacy & Trust Rules

- **CHAIR VERIFIED disclaimer:** Always present `CHAIR VERIFIED` as an independent platform verification badge—never imply government licensing or certification.
- **Critical hygiene override:** Failed mandatory checks (single-use razor blades, safe sharps disposal, disinfected reusable tools, fresh towels) must force inspection failure (`FAILED_CRITICAL`) regardless of numerical score and block/suspend verification.
- **Private assets:** `salon_documents` and `style_photos` must live in private storage, validate MIME/magic bytes/size on upload, and serve only via short-lived signed URLs to authorized users.
- **Completed-only reviews & eligibility:** Restrict `reviews` strictly to `COMPLETED` bookings owned by the reviewer; apply platform `commission_ledger` entries only to eligible `COMPLETED` platform-originated bookings.
- **Legal/CA boundary:** Do not fabricate Indian tax (GST/TCS), RBI Payment Aggregator, or DPDP legal advice—keep configurable rates in admin tables and flag compliance items in `docs/compliance-checklist.md`.
