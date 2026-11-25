---
trigger: glob
globs: "**/apps/mobile/**/*.ts, **/apps/mobile/**/*.tsx, **/apps/web/**/*.ts, **/apps/web/**/*.tsx, **/apps/web/**/*.css"
description: CHAIR visual direction, accessibility, i18n, and budget-device UI standards
---

# Frontend & CHAIR Design Standards

- **Brand palette:** Warm Ivory (`#FAF7F2` / `#F4EFE6`), Charcoal (`#1C1B19` / `#2D2B28`), Muted Olive (`#4A5D4E`), Subtle Bronze (`#9C744F`). Avoid generic SaaS purple/blue gradients, neon accents, or heavy glassmorphism.
- **Surface clarity:** Customer app is calm, editorial, and effortless; Partner PWA is high-contrast, fast, and scan-friendly under barbershop lighting.
- **5 required UI states:** Every async view must handle `loading`, `empty`, `error`, `offline`, and `permission-denied` states explicitly.
- **i18n-ready:** Never hardcode English user-facing copy in components—route all labels through `en` / `hi` translation dictionaries (`@chair/shared-types` i18n keys).
- **Budget Android & Accessibility:** Target `>= 48dp` (`44pt` iOS) touch targets, WCAG AA contrast, optimized compressed imagery, and virtualized lists (`FlashList` on RN).

```tsx
// ✅ GOOD
<Text>{t('booking.confirmCta')}</Text>

// ❌ BAD
<Text>Confirm Booking</Text>
```
