import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SafeAreaView } from "react-native-safe-area-context";
import { AlertCircle, CheckCircle2, Lock, ShieldCheck, Smartphone, WifiOff } from "lucide-react-native";
import {
  ALL_CONSENT_TYPES,
  getTranslations,
  isValidOtpCode,
  normalizePhoneE164,
  type ConsentType,
  type OTPRequestResponse,
  type SupportedLocale,
  type UserProfileDto,
} from "@chair/shared-types";
import {
  fetchMobileProfile,
  logoutMobileSession,
  MobileApiError,
  requestMobileOtp,
  updateMobileConsents,
  updateMobileProfile,
  verifyMobileOtp,
} from "@/services/authApi";
import { fetchMobileHealth } from "@/services/health";
import {
  clearMobileSession,
  loadMobileSession,
  mobileSessionFromTokens,
  saveMobileSession,
  type StoredMobileSession,
} from "@/services/tokenStorage";
import { MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "@/theme/tokens";

const CONSENT_KEYS: Record<
  ConsentType,
  {
    label:
      | "consentTermsLabel"
      | "consentPrivacyLabel"
      | "consentLocationLabel"
      | "consentStylePhotosLabel"
      | "consentMarketingLabel";
    desc:
      | "consentTermsDesc"
      | "consentPrivacyDesc"
      | "consentLocationDesc"
      | "consentStylePhotosDesc"
      | "consentMarketingDesc";
  }
> = {
  TERMS: { label: "consentTermsLabel", desc: "consentTermsDesc" },
  PRIVACY_DPDP: { label: "consentPrivacyLabel", desc: "consentPrivacyDesc" },
  LOCATION: { label: "consentLocationLabel", desc: "consentLocationDesc" },
  STYLE_PASSPORT_PHOTOS: { label: "consentStylePhotosLabel", desc: "consentStylePhotosDesc" },
  MARKETING: { label: "consentMarketingLabel", desc: "consentMarketingDesc" },
};

function formatMobileError(err: unknown, t: ReturnType<typeof getTranslations>): string {
  if (err instanceof MobileApiError) {
    if (err.code === "OFFLINE") {
      return t.states.offline;
    }
    if (err.code === "NETWORK_ERROR") {
      return t.states.networkError;
    }
    return err.message;
  }
  return err instanceof Error ? err.message : t.states.error;
}

export default function CustomerAuthScreen() {
  const [locale, setLocale] = useState<SupportedLocale>("en");
  const t = getTranslations(locale);

  const [session, setSession] = useState<StoredMobileSession | null>(null);
  const [sessionHydrating, setSessionHydrating] = useState(true);
  const [profile, setProfile] = useState<UserProfileDto | null>(null);

  const [authStep, setAuthStep] = useState<"phone" | "otp">("phone");
  const [phoneInput, setPhoneInput] = useState("");
  const [normalizedPhone, setNormalizedPhone] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<OTPRequestResponse | null>(null);
  const [otpInput, setOtpInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isOfflineError, setIsOfflineError] = useState(false);

  const [fullNameInput, setFullNameInput] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [consentMap, setConsentMap] = useState<Record<ConsentType, boolean>>({
    TERMS: false,
    PRIVACY_DPDP: false,
    LOCATION: false,
    STYLE_PASSPORT_PHOTOS: false,
    MARKETING: false,
  });
  const [statusNotice, setStatusNotice] = useState<string | null>(null);

  const healthQuery = useQuery({
    queryKey: ["foundation-health"],
    queryFn: () => fetchMobileHealth(),
  });

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const stored = await loadMobileSession();
        if (!active || !stored) {
          return;
        }
        setSession(stored);
        setLocale(stored.preferredLocale);
        const me = await fetchMobileProfile(stored, (next) => {
          setSession(next);
          if (!next) {
            setProfile(null);
          }
        });
        if (!active) {
          return;
        }
        setProfile(me);
        setLocale(me.preferred_locale);
        syncProfileForm(me);
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof MobileApiError && (err.status === 401 || err.status === 403)) {
          await clearMobileSession();
          setSession(null);
          setProfile(null);
        } else {
          setIsOfflineError(err instanceof MobileApiError && err.code === "OFFLINE");
          setAuthError(formatMobileError(err, getTranslations("en")));
        }
      } finally {
        if (active) {
          setSessionHydrating(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  function syncProfileFields(me: UserProfileDto) {
    setFullNameInput(me.full_name ?? "");
    setEmailInput(me.email ?? "");
  }

  function syncConsentFields(me: UserProfileDto) {
    const nextConsents = {
      TERMS: false,
      PRIVACY_DPDP: false,
      LOCATION: false,
      STYLE_PASSPORT_PHOTOS: false,
      MARKETING: false,
    };
    for (const ctype of ALL_CONSENT_TYPES) {
      const found = me.consents.find((c) => c.consent_type === ctype);
      nextConsents[ctype] = Boolean(found?.granted);
    }
    setConsentMap(nextConsents);
  }

  function syncProfileForm(me: UserProfileDto) {
    syncProfileFields(me);
    syncConsentFields(me);
  }

  const sendOtpMutation = useMutation({
    mutationFn: async () => {
      const e164 = normalizePhoneE164(phoneInput);
      if (!e164) {
        throw new MobileApiError(422, "INVALID_PHONE", t.auth.phoneError);
      }
      const res = await requestMobileOtp({ phone_e164: e164 });
      return { e164, res };
    },
    onSuccess: ({ e164, res }) => {
      setAuthError(null);
      setIsOfflineError(false);
      setNormalizedPhone(e164);
      setChallenge(res);
      setOtpInput("");
      setAuthStep("otp");
    },
    onError: (err) => {
      setIsOfflineError(err instanceof MobileApiError && err.code === "OFFLINE");
      setAuthError(formatMobileError(err, t));
    },
  });

  const verifyOtpMutation = useMutation({
    mutationFn: async () => {
      if (!challenge || !normalizedPhone || !isValidOtpCode(otpInput)) {
        throw new MobileApiError(422, "INVALID_OTP", t.auth.otpError);
      }
      const tokens = await verifyMobileOtp({
        challenge_id: challenge.challenge_id,
        phone_e164: normalizedPhone,
        otp_code: otpInput.trim(),
      });
      const stored = mobileSessionFromTokens(tokens);
      await saveMobileSession(stored);
      const me = await fetchMobileProfile(stored);
      return { stored, me };
    },
    onSuccess: ({ stored, me }) => {
      setAuthError(null);
      setIsOfflineError(false);
      setSession(stored);
      setProfile(me);
      setLocale(me.preferred_locale);
      syncProfileForm(me);
    },
    onError: (err) => {
      setIsOfflineError(err instanceof MobileApiError && err.code === "OFFLINE");
      setAuthError(formatMobileError(err, t));
    },
  });

  const saveProfileMutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      const trimmedEmail = emailInput.trim().toLowerCase();
      if (trimmedEmail.length > 0 && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmedEmail)) {
        throw new MobileApiError(422, "INVALID_EMAIL", t.profile.emailError);
      }
      return updateMobileProfile(
        session,
        {
          full_name: fullNameInput.trim() || null,
          email: trimmedEmail || null,
          preferred_locale: locale,
        },
        (next) => setSession(next)
      );
    },
    onSuccess: (updated) => {
      setAuthError(null);
      setProfile((prev) => (prev ? { ...prev, ...updated, consents: prev.consents } : updated));
      syncProfileFields(updated);
      setStatusNotice(t.profile.profileSaved);
    },
    onError: (err) => {
      setStatusNotice(null);
      setAuthError(formatMobileError(err, t));
    },
  });

  const saveConsentsMutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      return updateMobileConsents(
        session,
        {
          decisions: ALL_CONSENT_TYPES.map((ctype) => ({
            consent_type: ctype,
            granted: consentMap[ctype],
            version: "v1.0",
          })),
        },
        (next) => setSession(next)
      );
    },
    onSuccess: (updatedConsents) => {
      setAuthError(null);
      setProfile((prev) => (prev ? { ...prev, consents: updatedConsents.consents } : prev));
      setStatusNotice(t.consents.savedNotice);
    },
    onError: (err) => {
      setStatusNotice(null);
      setAuthError(formatMobileError(err, t));
    },
  });

  async function handleSignOut() {
    if (!session) {
      return;
    }
    try {
      await logoutMobileSession(session);
    } catch {
      // Clear local UI state cleanly even if network/token revoke fails.
    } finally {
      setSession(null);
      setProfile(null);
      setAuthError(null);
      setIsOfflineError(false);
      setAuthStep("phone");
      setStatusNotice(null);
    }
  }

  const probe = healthQuery.data;

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.headerRow}>
          <View style={styles.brandBlock}>
            <Text style={styles.titleText}>
              {t.brand.name} · {t.surfaces.customer}
            </Text>
          </View>

          <View style={styles.langRow}>
            {(["en", "hi"] as const).map((lang) => (
              <Pressable
                key={lang}
                accessibilityRole="button"
                accessibilityState={{ selected: locale === lang }}
                onPress={() => setLocale(lang)}
                style={[styles.langButton, locale === lang && styles.langButtonActive]}
              >
                <Text
                  style={[
                    styles.langButtonText,
                    locale === lang && styles.langButtonTextActive,
                  ]}
                >
                  {lang === "en" ? "EN" : "हिन्दी"}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {isOfflineError && (
          <View style={styles.offlineBox}>
            <WifiOff size={18} color={MOBILE_THEME.colors.bronzeAccent} />
            <Text style={styles.detailText}>{t.states.offline}</Text>
          </View>
        )}

        {authError && (
          <View style={styles.errorBox}>
            <View style={styles.stateRow}>
              <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
              <Text style={styles.errorTitle}>{authError}</Text>
            </View>
          </View>
        )}

        {statusNotice && (
          <View style={styles.noticeBox}>
            <CheckCircle2 size={18} color={MOBILE_THEME.colors.olivePrimary} />
            <Text style={styles.okTitle}>{statusNotice}</Text>
          </View>
        )}

        {sessionHydrating ? (
          <View style={styles.panel}>
            <View style={styles.stateRow}>
              <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
              <Text style={styles.stateText}>{t.states.loading}</Text>
            </View>
          </View>
        ) : !session || !profile ? (
          <View style={styles.panel}>
            <View style={styles.stateRow}>
              <Smartphone size={20} color={MOBILE_THEME.colors.olivePrimary} />
              <Text style={styles.sectionTitle}>
                {authStep === "phone" ? t.auth.signInHeading : t.auth.otpHeading}
              </Text>
            </View>
            <Text style={styles.noticeText}>{t.auth.signInSubtitle}</Text>

            {authStep === "phone" ? (
              <View style={styles.formBlock}>
                <Text style={styles.fieldLabel}>{t.auth.phoneLabel}</Text>
                <Text style={styles.hintText}>{t.auth.phoneHint}</Text>
                <TextInput
                  value={phoneInput}
                  onChangeText={setPhoneInput}
                  keyboardType="phone-pad"
                  textContentType="telephoneNumber"
                  autoComplete="tel"
                  autoCapitalize="none"
                  placeholder="+919000000003"
                  placeholderTextColor={MOBILE_THEME.colors.charcoalMuted}
                  style={styles.input}
                />
                <Pressable
                  accessibilityRole="button"
                  disabled={sendOtpMutation.isPending}
                  onPress={() => sendOtpMutation.mutate()}
                  style={styles.primaryButton}
                >
                  <Text style={styles.primaryButtonText}>
                    {sendOtpMutation.isPending ? t.auth.sendingOtp : t.auth.requestOtpButton}
                  </Text>
                </Pressable>
              </View>
            ) : (
              <View style={styles.formBlock}>
                {challenge && (
                  <View style={styles.challengeBox}>
                    <Text style={styles.fieldLabel}>
                      {t.auth.otpSentPrefix} {challenge.masked_phone}
                    </Text>
                    {challenge.delivery_mode === "mock" && (
                      <Text style={styles.hintText}>{t.auth.mockOtpHint}</Text>
                    )}
                  </View>
                )}
                <Text style={styles.fieldLabel}>{t.auth.otpLabel}</Text>
                <Text style={styles.hintText}>{t.auth.otpHint}</Text>
                <TextInput
                  value={otpInput}
                  onChangeText={setOtpInput}
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  autoComplete="sms-otp"
                  maxLength={6}
                  placeholder="123456"
                  placeholderTextColor={MOBILE_THEME.colors.charcoalMuted}
                  style={styles.input}
                />
                <View style={styles.buttonRow}>
                  <Pressable
                    accessibilityRole="button"
                    disabled={verifyOtpMutation.isPending}
                    onPress={() => verifyOtpMutation.mutate()}
                    style={styles.primaryButton}
                  >
                    <Text style={styles.primaryButtonText}>
                      {verifyOtpMutation.isPending
                        ? t.auth.verifyingOtp
                        : t.auth.verifyOtpButton}
                    </Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    disabled={sendOtpMutation.isPending || verifyOtpMutation.isPending}
                    onPress={() => sendOtpMutation.mutate()}
                    style={styles.secondaryButton}
                  >
                    <Text style={styles.secondaryButtonText}>{t.auth.resendOtpButton}</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => {
                      setAuthError(null);
                      setAuthStep("phone");
                    }}
                    style={styles.secondaryButton}
                  >
                    <Text style={styles.secondaryButtonText}>{t.auth.changePhoneButton}</Text>
                  </Pressable>
                </View>
              </View>
            )}
          </View>
        ) : (
          <>
            <View style={styles.panel}>
              <View style={styles.headerRow}>
                <View style={styles.brandBlock}>
                  <Text style={styles.sectionTitle}>
                    {t.auth.signedInAs} {profile.full_name || profile.phone_e164}
                  </Text>
                  <Text style={styles.hintText}>
                    {t.auth.activeRolesLabel}: {profile.roles.map((r) => r.role).join(", ")}
                  </Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => void handleSignOut()}
                  style={styles.secondaryButton}
                >
                  <Text style={styles.secondaryButtonText}>{t.auth.signOutButton}</Text>
                </Pressable>
              </View>

              {!profile.is_active && (
                <View style={styles.errorBox}>
                  <Lock size={16} color={MOBILE_THEME.colors.danger} />
                  <Text style={styles.errorTitle}>{t.states.permissionDenied}</Text>
                </View>
              )}

              <Text style={styles.fieldLabel}>{t.profile.fullNameLabel}</Text>
              <TextInput
                value={fullNameInput}
                onChangeText={setFullNameInput}
                autoComplete="name"
                maxLength={120}
                placeholder={t.profile.noNameYet}
                placeholderTextColor={MOBILE_THEME.colors.charcoalMuted}
                style={styles.input}
              />

              <Text style={styles.fieldLabel}>{t.profile.emailLabel}</Text>
              <TextInput
                value={emailInput}
                onChangeText={setEmailInput}
                keyboardType="email-address"
                autoComplete="email"
                autoCapitalize="none"
                placeholder="name@example.com"
                placeholderTextColor={MOBILE_THEME.colors.charcoalMuted}
                style={styles.input}
              />

              <Pressable
                accessibilityRole="button"
                disabled={saveProfileMutation.isPending}
                onPress={() => saveProfileMutation.mutate()}
                style={styles.darkButton}
              >
                <Text style={styles.primaryButtonText}>
                  {saveProfileMutation.isPending
                    ? t.profile.savingProfile
                    : t.profile.saveProfileButton}
                </Text>
              </Pressable>
            </View>

            <View style={styles.panel}>
              <Text style={styles.sectionTitle}>{t.consents.sectionHeading}</Text>
              <Text style={styles.hintText}>{t.consents.sectionDescription}</Text>

              {ALL_CONSENT_TYPES.map((ctype) => {
                const keys = CONSENT_KEYS[ctype];
                return (
                  <View key={ctype} style={styles.consentRow}>
                    <View style={styles.brandBlock}>
                      <Text style={styles.fieldLabel}>{t.consents[keys.label]}</Text>
                      <Text style={styles.hintText}>{t.consents[keys.desc]}</Text>
                    </View>
                    <Switch
                      accessibilityLabel={t.consents[keys.label]}
                      value={consentMap[ctype]}
                      onValueChange={(nextVal) =>
                        setConsentMap((prev) => ({ ...prev, [ctype]: nextVal }))
                      }
                      trackColor={{
                        false: MOBILE_THEME.colors.ivoryBorder,
                        true: MOBILE_THEME.colors.olivePrimary,
                      }}
                    />
                  </View>
                );
              })}

              <Pressable
                accessibilityRole="button"
                disabled={saveConsentsMutation.isPending}
                onPress={() => saveConsentsMutation.mutate()}
                style={styles.primaryButton}
              >
                <Text style={styles.primaryButtonText}>
                  {saveConsentsMutation.isPending
                    ? t.consents.saving
                    : t.consents.saveButton}
                </Text>
              </Pressable>
            </View>
          </>
        )}

        <View style={styles.panel}>
          <Text style={styles.hintText}>{t.health.phaseNotice}</Text>
          {healthQuery.isPending ? (
            <View style={styles.stateRow}>
              <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
              <Text style={styles.stateText}>{t.states.loading}</Text>
            </View>
          ) : probe?.state === "error" ? (
            <View style={styles.errorBox}>
              <Text style={styles.errorTitle}>{t.states.error}</Text>
              <Pressable
                accessibilityRole="button"
                onPress={() => void healthQuery.refetch()}
                style={styles.secondaryButton}
              >
                <Text style={styles.secondaryButtonText}>{t.health.retry}</Text>
              </Pressable>
            </View>
          ) : probe?.state === "ok" ? (
            <Text style={styles.detailText}>
              {probe.data.status === "ok" ? t.health.statusOk : t.health.statusDegraded} ·{" "}
              {t.health.database}: {probe.data.checks.database.status} · {t.health.postgis}:{" "}
              {probe.data.checks.postgis.status} · {t.health.redis}: {probe.data.checks.redis.status}
            </Text>
          ) : (
            <Text style={styles.detailText}>{t.states.empty}</Text>
          )}
        </View>

        <View style={styles.footer}>
          <ShieldCheck size={16} color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.disclaimer}>
            {t.brand.verifiedBadge}: {t.brand.verifiedDisclaimer}
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
  },
  container: {
    padding: MOBILE_THEME.spacing.lg,
    gap: MOBILE_THEME.spacing.lg,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.md,
  },
  brandBlock: {
    flex: 1,
  },
  titleText: {
    fontSize: 22,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  langRow: {
    flexDirection: "row",
    gap: MOBILE_THEME.spacing.sm,
  },
  langButton: {
    minWidth: TOUCH_TARGET_MIN_DP,
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 12,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    alignItems: "center",
    justifyContent: "center",
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
  panel: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    gap: MOBILE_THEME.spacing.md,
  },
  formBlock: {
    gap: MOBILE_THEME.spacing.sm,
  },
  fieldLabel: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  hintText: {
    fontSize: 12,
    lineHeight: 18,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  noticeText: {
    fontSize: 14,
    lineHeight: 20,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  input: {
    minHeight: TOUCH_TARGET_MIN_DP,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    paddingHorizontal: 14,
    fontSize: 16,
    color: MOBILE_THEME.colors.charcoalInk,
  },
  buttonRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: MOBILE_THEME.spacing.sm,
  },
  primaryButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 18,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({
      web: { cursor: "pointer" as unknown as undefined },
    }),
  },
  darkButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 18,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.charcoalInk,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryButtonText: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.white,
  },
  secondaryButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 14,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  consentRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: MOBILE_THEME.spacing.md,
    minHeight: TOUCH_TARGET_MIN_DP,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
  },
  challengeBox: {
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    gap: 4,
  },
  noticeBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  offlineBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.bronzeAccent,
  },
  stateRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
  },
  stateText: {
    fontSize: 14,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  errorBox: {
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
    gap: MOBILE_THEME.spacing.sm,
  },
  errorTitle: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  okTitle: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  detailText: {
    fontSize: 13,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  footer: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: MOBILE_THEME.spacing.sm,
  },
  disclaimer: {
    flex: 1,
    fontSize: 12,
    lineHeight: 18,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
});
