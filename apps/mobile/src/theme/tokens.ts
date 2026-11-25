import { CHAIR_PALETTE } from "@chair/shared-types";

export const TOUCH_TARGET_MIN_DP = 48;
export const IOS_TOUCH_TARGET_MIN_PT = 44;

export const MOBILE_THEME = {
  colors: CHAIR_PALETTE,
  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
  },
  radii: {
    sm: 6,
    md: 10,
    lg: 14,
    pill: 999,
  },
} as const;
