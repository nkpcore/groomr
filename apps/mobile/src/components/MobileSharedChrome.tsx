import { Platform, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from "react-native";
import { ShieldCheck } from "lucide-react-native";
import type { SupportedLocale, TranslationCatalog } from "@chair/shared-types";
import { MobileApiError } from "@/services/http";
import { MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "@/theme/tokens";

export function formatMobileError(err: unknown, t: TranslationCatalog): string {
  if (err instanceof MobileApiError) {
    if (err.code === "OFFLINE") {
      return t.states.offline;
    }
    if (err.code === "NETWORK_ERROR" || /^HTTP_\d+$/.test(err.code)) {
      return err.code === "NETWORK_ERROR" ? t.states.networkError : t.states.error;
    }
    return err.message;
  }
  return t.states.error;
}

export function LanguageSwitcher({
  locale,
  onChange,
}: {
  locale: SupportedLocale;
  onChange: (next: SupportedLocale) => void;
}) {
  return (
    <View style={styles.langRow}>
      {(["en", "hi"] as const).map((lang) => {
        const selected = locale === lang;
        return (
          <Pressable
            key={lang}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => onChange(lang)}
            style={[styles.langButton, selected && styles.langButtonActive]}
          >
            <Text style={[styles.langButtonText, selected && styles.langButtonTextActive]}>
              {lang === "en" ? "EN" : "हिन्दी"}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function VerifiedDisclaimerFooter({
  disclaimerText,
  style,
}: {
  disclaimerText: string;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.footer, style]}>
      <ShieldCheck size={16} color={MOBILE_THEME.colors.olivePrimary} />
      <Text style={styles.disclaimer}>{disclaimerText}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  langRow: {
    flexDirection: "row",
    gap: 6,
  },
  langButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    minWidth: 52,
    paddingHorizontal: 12,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({
      web: { cursor: "pointer" as unknown as undefined },
    }),
  },
  langButtonActive: {
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  langButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  langButtonTextActive: {
    color: MOBILE_THEME.colors.white,
  },
  footer: {
    flexDirection: "row",
    gap: 8,
    alignItems: "flex-start",
    paddingVertical: MOBILE_THEME.spacing.md,
    borderTopWidth: 1,
    borderTopColor: MOBILE_THEME.colors.ivoryBorder,
    marginTop: MOBILE_THEME.spacing.sm,
  },
  disclaimer: {
    flex: 1,
    fontSize: 12,
    lineHeight: 18,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
});
