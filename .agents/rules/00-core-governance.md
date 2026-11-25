---
trigger: always_on
description: Core repository governance, phased delivery, and verification discipline
---

# Core Governance

- Inspect existing files, git status, and dependencies before editing.
- Execute strictly within the active phase in `docs/plans/roadmap.md`; do not jump ahead to unapproved screens.
- Never commit `.env` or real secrets; update `.env.example` when adding configuration keys.
- Label every seeded salon, barber, booking, and review fixture clearly as `[DEMO]` data.
- Never ship dead buttons, hardcoded fake availability, fabricated ratings, or fake payment success states.
- Run lint, typecheck, and relevant unit/integration tests after edits; report exact failures or skipped checks honestly.

```text
# ✅ GOOD: Inspect -> Implement Active Phase -> Verify -> Report
# ❌ BAD: Generate all 40 screens with mocked "Payment Succeeded!" alerts
```
