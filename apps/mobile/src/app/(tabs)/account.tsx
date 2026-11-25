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
import { AlertCircle, CheckCircle2, Lock, Smartphone, WifiOff } from "lucide-react-native";
import {
  ALL_CONSENT_TYPES,
  isValidOtpCode,
  normalizePhoneE164,
  type ConsentType,
  type OTPRequestResponse,
} from "@chair/shared-types";
import {
  LanguageSwitcher,
  VerifiedDisclaimerFooter,
  formatMobileError,
} from "@/components/MobileSharedChrome";
import { useMobileApp } from "@/context/MobileAppContext";
import {
  fetchMobileProfile,
  MobileApiError,
  requestMobileOtp,
  updateMobileConsents,
  updateMobileProfile,
  verifyMobileOtp,
} from "@/services/authApi";
import { fetchMobileHealth } from "@/services/health";
import { mobileSessionFromTokens, saveMobileSession } from "@/services/tokenStorage";
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

export default function CustomerAccountScreen() {
  const {
    locale,
    setLocale,
    t,
    session,
    setSession,
    profile,
    setProfile,
    sessionHydrating,
    hydrationError,
    retryHydration,
    handleSignOut,
  } = useMobileApp();

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

  const profileId = profile?.id ?? null;
  const profileFullName = profile?.full_name ?? "";
  const profileEmail = profile?.email ?? "";
  const profileConsents = profile?.consents;

  useEffect(() => {
    if (profileId) {
      setFullNameInput(profileFullName);
      setEmailInput(profileEmail);
    }
  }, [profileId, profileFullName, profileEmail]);

  useEffect(() => {
    if (profileId && profileConsents) {
      const nextConsents: Record<ConsentType, boolean> = {
        TERMS: false,
        PRIVACY_DPDP: false,
        LOCATION: false,
        STYLE_PASSPORT_PHOTOS: false,
        MARKETING: false,
      };
      for (const ctype of ALL_CONSENT_TYPES) {
        const found = profileConsents.find((c) => c.consent_type === ctype);
        nextConsents[ctype] = Boolean(found?.granted);
      }
      setConsentMap(nextConsents);
    }
  }, [profileId, profileConsents]);

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
      setSession(stored);
      const me = await fetchMobileProfile(stored, (next) => {
        setSession(next);
        if (!next) {
          setProfile(null);
        }
      });
      return { stored, me };
    },
    onSuccess: ({ stored, me }) => {
      setAuthError(null);
      setIsOfflineError(false);
      setSession(stored);
      setProfile(me);
      setLocale(me.preferred_locale);
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
        (next) => {
          setSession(next);
          if (!next) {
            setProfile(null);
          }
        }
      );
    },
    onSuccess: (updated) => {
      setAuthError(null);
      setProfile((prev) => (prev ? { ...prev, ...updated, consents: prev.consents } : updated));
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
        (next) => {
          setSession(next);
          if (!next) {
            setProfile(null);
          }
        }
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

  async function onSignOutPress() {
    await handleSignOut();
    setAuthError(null);
    setIsOfflineError(false);
    setAuthStep("phone");
    setStatusNotice(null);
  }

  const probe = healthQuery.data;

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.headerRow}>
          <View style={styles.brandBlock}>
            <Text style={styles.titleText}>{t.navigation.accountTab}</Text>
          </View>

          <LanguageSwitcher locale={locale} onChange={setLocale} />
        </View>

        {(isOfflineError || hydrationError === "offline") && !(session && !profile) && (
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
        ) : session && !profile ? (
          <View style={styles.panel}>
            <View style={styles.stateRow}>
              {hydrationError === "offline" || isOfflineError ? (
                <WifiOff size={20} color={MOBILE_THEME.colors.bronzeAccent} />
              ) : (
                <AlertCircle size={20} color={MOBILE_THEME.colors.danger} />
              )}
              <Text style={styles.sectionTitle}>
                {hydrationError === "offline" || isOfflineError
                  ? t.states.offline
                  : t.states.networkError}
              </Text>
            </View>
            <Text style={styles.noticeText}>{t.states.error}</Text>
            <View style={styles.buttonRow}>
              <Pressable
                accessibilityRole="button"
                onPress={() => void retryHydration()}
                style={styles.primaryButton}
              >
                <Text style={styles.primaryButtonText}>{t.health.retry}</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                onPress={() => void onSignOutPress()}
                style={styles.secondaryButton}
              >
                <Text style={styles.secondaryButtonText}>{t.auth.signOutButton}</Text>
              </Pressable>
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
                  onPress={() => void onSignOutPress()}
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
                const checked = consentMap[ctype];
                return (
                  <Pressable
                    key={ctype}
                    accessibilityRole="switch"
                    accessibilityLabel={t.consents[keys.label]}
                    accessibilityState={{ checked }}
                    onPress={() =>
                      setConsentMap((prev) => ({ ...prev, [ctype]: !prev[ctype] }))
                    }
                    style={styles.consentRow}
                  >
                    <View style={styles.brandBlock}>
                      <Text style={styles.fieldLabel}>{t.consents[keys.label]}</Text>
                      <Text style={styles.hintText}>{t.consents[keys.desc]}</Text>
                    </View>
                    <View pointerEvents="none">
                      <Switch
                        accessible={false}
                        value={checked}
                        trackColor={{
                          false: MOBILE_THEME.colors.ivoryBorder,
                          true: MOBILE_THEME.colors.olivePrimary,
                        }}
                      />
                    </View>
                  </Pressable>
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

        <VerifiedDisclaimerFooter
          disclaimerText={`${t.brand.verifiedBadge}: ${t.brand.verifiedDisclaimer}`}
        />
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
});
