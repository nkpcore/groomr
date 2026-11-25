import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AlertCircle,
  ArrowLeft,
  Clock,
  CreditCard,
  Lock,
  Store,
  WifiOff,
} from "lucide-react-native";
import {
  formatDurationMinutes,
  formatINRFromPaise,
  formatIstDateTime,
  formatIstTimeSlot,
} from "@chair/shared-types";
import { VerifiedDisclaimerFooter, formatMobileError } from "@/components/MobileSharedChrome";
import { useMobileApp } from "@/context/MobileAppContext";
import {
  captureTestModePayment,
  confirmPayAtSalon,
  createPaymentOrder,
  fetchHoldDetail,
  makeMobileIdempotencyKey,
  releaseSlotHold,
} from "@/services/bookingsApi";
import { MobileApiError } from "@/services/http";
import { MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "@/theme/tokens";

export default function HoldCheckoutScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const holdId = typeof id === "string" ? id : "";
  const { locale, session, setSession, setProfile, t } = useMobileApp();

  const pasKeyRef = useRef<string>(makeMobileIdempotencyKey(`pas-${holdId}`));
  const orderKeyRef = useRef<string>(makeMobileIdempotencyKey(`ord-${holdId}`));
  const captureKeyRef = useRef<string>(makeMobileIdempotencyKey(`cap-${holdId}`));

  useEffect(() => {
    pasKeyRef.current = makeMobileIdempotencyKey(`pas-${holdId}`);
    orderKeyRef.current = makeMobileIdempotencyKey(`ord-${holdId}`);
    captureKeyRef.current = makeMobileIdempotencyKey(`cap-${holdId}`);
  }, [holdId]);

  const handleSessionUpdate = (next: typeof session) => {
    setSession(next);
    if (!next) {
      setProfile(null);
    }
  };

  const holdQuery = useQuery({
    queryKey: ["mobile-hold", holdId],
    enabled: Boolean(session && holdId),
    queryFn: () => fetchHoldDetail(session!, holdId, handleSessionUpdate),
  });

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const holdData = holdQuery.data;
  const remainingSeconds = useMemo(() => {
    if (!holdData || holdData.hold_status !== "ACTIVE") {
      return 0;
    }
    const expiresMs = Date.parse(holdData.expires_at);
    if (Number.isNaN(expiresMs)) {
      return 0;
    }
    return Math.max(0, Math.floor((expiresMs - nowMs) / 1000));
  }, [holdData, nowMs]);

  const countdownLabel = useMemo(() => {
    const mins = Math.floor(remainingSeconds / 60);
    const secs = remainingSeconds % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }, [remainingSeconds]);

  const [actionError, setActionError] = useState<string | null>(null);

  const confirmPayAtSalonMutation = useMutation({
    mutationFn: async () => {
      if (!session || !holdData) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      return confirmPayAtSalon(
        session,
        holdData.booking.id,
        handleSessionUpdate,
        pasKeyRef.current
      );
    },
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["mobile-hold", holdId] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-bookings"] });
      void queryClient.invalidateQueries({ queryKey: ["branch-availability"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-branches"] });
      router.replace("/(tabs)/bookings");
    },
    onError: (err) => {
      setActionError(formatMobileError(err, t));
    },
  });

  const payOnlineMutation = useMutation({
    mutationFn: async () => {
      if (!session || !holdData) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      const order = await createPaymentOrder(
        session,
        holdData.booking.id,
        handleSessionUpdate,
        orderKeyRef.current
      );
      return captureTestModePayment(
        session,
        holdData.booking.id,
        order.provider_order_id,
        handleSessionUpdate,
        captureKeyRef.current
      );
    },
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["mobile-hold", holdId] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-bookings"] });
      void queryClient.invalidateQueries({ queryKey: ["branch-availability"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-branches"] });
      router.replace("/(tabs)/bookings");
    },
    onError: (err) => {
      setActionError(formatMobileError(err, t));
    },
  });

  const releaseHoldMutation = useMutation({
    mutationFn: async () => {
      if (!session || !holdId) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      return releaseSlotHold(session, holdId, handleSessionUpdate);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mobile-hold", holdId] });
      void queryClient.invalidateQueries({ queryKey: ["branch-availability"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-branches"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-bookings"] });
      if (holdData?.booking.branch_id) {
        router.replace({
          pathname: "/branch/[id]",
          params: { id: holdData.booking.branch_id },
        });
      } else {
        router.replace("/(tabs)");
      }
    },
    onError: (err) => {
      setActionError(formatMobileError(err, t));
    },
  });

  const holdErr = holdQuery.error instanceof MobileApiError ? holdQuery.error : null;
  const isAlreadyConverted =
    Boolean(holdData) &&
    (holdData?.hold_status === "CONVERTED" || holdData?.booking.status === "CONFIRMED");
  const isExpired =
    Boolean(holdData) &&
    !isAlreadyConverted &&
    (holdData?.hold_status !== "ACTIVE" ||
      holdData?.booking.status === "EXPIRED" ||
      remainingSeconds === 0);
  const busy =
    confirmPayAtSalonMutation.isPending ||
    payOnlineMutation.isPending ||
    releaseHoldMutation.isPending;

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.topNav}>
        <Pressable
          accessibilityRole="button"
          onPress={() => {
            if (router.canGoBack()) {
              router.back();
            } else {
              router.replace("/(tabs)");
            }
          }}
          style={styles.backButton}
        >
          <ArrowLeft size={18} color={MOBILE_THEME.colors.charcoalInk} />
          <Text style={styles.backText}>{t.checkout.backToBranch}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.headerBlock}>
          <Text style={styles.titleText}>{t.checkout.heading}</Text>
          <Text style={styles.mutedText}>{t.checkout.subtitle}</Text>
        </View>

        {!session ? (
          <View style={styles.card}>
            <View style={styles.rowGapSm}>
              <Lock size={18} color={MOBILE_THEME.colors.danger} />
              <Text style={styles.cardTitle}>{t.bookings.signInRequired}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              onPress={() => router.replace("/(tabs)/account")}
              style={styles.primaryButton}
            >
              <Text style={styles.primaryButtonText}>{t.branch.openAccountButton}</Text>
            </Pressable>
          </View>
        ) : holdQuery.isPending ? (
          <View style={styles.card}>
            <View style={styles.rowGapSm}>
              <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
              <Text style={styles.mutedText}>{t.states.loading}</Text>
            </View>
          </View>
        ) : holdQuery.isError ? (
          <View style={styles.errorCard}>
            <View style={styles.rowGapSm}>
              {holdErr?.code === "OFFLINE" ? (
                <WifiOff size={18} color={MOBILE_THEME.colors.bronzeAccent} />
              ) : (
                <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
              )}
              <Text style={styles.errorTitle}>{formatMobileError(holdQuery.error, t)}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              onPress={() => void holdQuery.refetch()}
              style={styles.darkButton}
            >
              <Text style={styles.primaryButtonText}>{t.health.retry}</Text>
            </Pressable>
          </View>
        ) : holdData ? (
          <>
            <View
              style={[
                styles.timerBanner,
                isAlreadyConverted
                  ? styles.timerBannerActive
                  : isExpired
                    ? styles.timerBannerExpired
                    : styles.timerBannerActive,
              ]}
            >
              <Clock
                size={18}
                color={
                  isExpired ? MOBILE_THEME.colors.danger : MOBILE_THEME.colors.olivePrimary
                }
              />
              <Text style={styles.timerLabel}>
                {isAlreadyConverted
                  ? t.bookings.statusCONFIRMED
                  : isExpired
                    ? t.checkout.expiredNotice
                    : `${t.checkout.expiresInLabel}: ${countdownLabel}`}
              </Text>
            </View>

            {actionError && (
              <View style={styles.errorCard}>
                <View style={styles.rowGapSm}>
                  <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
                  <Text style={styles.errorTitle}>{actionError}</Text>
                </View>
              </View>
            )}

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>{t.checkout.salonSummaryHeading}</Text>
              <Text style={styles.cardTitle}>{holdData.booking.branch_name}</Text>
              <Text style={styles.mutedText}>
                {formatIstDateTime(holdData.booking.scheduled_start_at, locale)} (
                {formatIstTimeSlot(holdData.booking.scheduled_start_at, locale)} -{" "}
                {formatIstTimeSlot(holdData.booking.scheduled_end_at, locale)})
              </Text>
              {holdData.booking.staff_name && (
                <Text style={styles.metaText}>
                  {t.checkout.barberLabel}: {holdData.booking.staff_name}
                </Text>
              )}
              {holdData.booking.resource_name && (
                <Text style={styles.metaText}>
                  {t.checkout.chairLabel}: {holdData.booking.resource_name}
                </Text>
              )}

              <View style={styles.itemsList}>
                {holdData.booking.items.map((item) => (
                  <View key={item.id} style={styles.itemRow}>
                    <Text style={styles.itemName}>
                      {item.service_name_snapshot} (
                      {formatDurationMinutes(item.duration_minutes_snapshot, locale)})
                    </Text>
                    <Text style={styles.itemPrice}>
                      {formatINRFromPaise(item.unit_price_paise_snapshot)}
                    </Text>
                  </View>
                ))}
              </View>

              <View style={styles.totalRow}>
                <Text style={styles.totalLabel}>{t.branch.totalPriceLabel}</Text>
                <Text style={styles.totalAmount}>
                  {formatINRFromPaise(holdData.booking.net_payable_paise)}
                </Text>
              </View>
            </View>

            {isAlreadyConverted ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => router.replace("/(tabs)/bookings")}
                style={styles.primaryButton}
              >
                <Text style={styles.primaryButtonText}>{t.navigation.bookingsTab}</Text>
              </Pressable>
            ) : isExpired ? (
              <Pressable
                accessibilityRole="button"
                onPress={() =>
                  router.replace({
                    pathname: "/branch/[id]",
                    params: { id: holdData.booking.branch_id },
                  })
                }
                style={styles.darkButton}
              >
                <Text style={styles.primaryButtonText}>{t.checkout.pickAnotherSlot}</Text>
              </Pressable>
            ) : (
              <View style={styles.card}>
                <Text style={styles.sectionTitle}>{t.checkout.paymentMethodHeading}</Text>

                <View style={styles.paymentOptionBox}>
                  <View style={styles.rowGapSm}>
                    <Store size={18} color={MOBILE_THEME.colors.olivePrimary} />
                    <Text style={styles.cardTitle}>{t.checkout.payAtSalonTitle}</Text>
                  </View>
                  <Text style={styles.mutedText}>{t.checkout.payAtSalonDesc}</Text>
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy}
                    onPress={() => confirmPayAtSalonMutation.mutate()}
                    style={styles.primaryButton}
                  >
                    <Text style={styles.primaryButtonText}>
                      {confirmPayAtSalonMutation.isPending
                        ? t.checkout.processingPayment
                        : t.checkout.confirmPayAtSalon}
                    </Text>
                  </Pressable>
                </View>

                <View style={styles.paymentOptionBox}>
                  <View style={styles.rowGapSm}>
                    <CreditCard size={18} color={MOBILE_THEME.colors.bronzeAccent} />
                    <Text style={styles.cardTitle}>{t.checkout.payOnlineTitle}</Text>
                  </View>
                  <Text style={styles.mutedText}>{t.checkout.payOnlineDesc}</Text>
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy}
                    onPress={() => payOnlineMutation.mutate()}
                    style={styles.darkButton}
                  >
                    <Text style={styles.primaryButtonText}>
                      {payOnlineMutation.isPending
                        ? t.checkout.processingPayment
                        : `${t.checkout.payOnlineCta} (${formatINRFromPaise(
                            holdData.booking.net_payable_paise
                          )})`}
                    </Text>
                  </Pressable>
                </View>

                <Pressable
                  accessibilityRole="button"
                  disabled={busy}
                  onPress={() => releaseHoldMutation.mutate()}
                  style={styles.secondaryButton}
                >
                  <Text style={styles.secondaryButtonText}>
                    {releaseHoldMutation.isPending
                      ? t.checkout.releasingHold
                      : t.checkout.releaseHoldButton}
                  </Text>
                </Pressable>
              </View>
            )}

            <VerifiedDisclaimerFooter
              disclaimerText={`${t.brand.verifiedBadge}: ${t.brand.verifiedDisclaimer}`}
            />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
  },
  topNav: {
    paddingHorizontal: MOBILE_THEME.spacing.lg,
    paddingTop: MOBILE_THEME.spacing.sm,
    paddingBottom: MOBILE_THEME.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: MOBILE_THEME.colors.ivoryBorder,
  },
  backButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    alignSelf: "flex-start",
    ...Platform.select({ web: { cursor: "pointer" as unknown as undefined } }),
  },
  backText: {
    fontSize: 15,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  container: {
    padding: MOBILE_THEME.spacing.lg,
    gap: MOBILE_THEME.spacing.md,
    paddingBottom: MOBILE_THEME.spacing.xl,
  },
  headerBlock: {
    gap: 4,
  },
  titleText: {
    fontSize: 22,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  card: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    gap: MOBILE_THEME.spacing.sm,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  mutedText: {
    fontSize: 13,
    lineHeight: 19,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  metaText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  rowGapSm: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  timerBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
  },
  timerBannerActive: {
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  timerBannerExpired: {
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
    borderColor: MOBILE_THEME.colors.danger,
  },
  timerLabel: {
    flex: 1,
    fontSize: 14,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  itemsList: {
    marginTop: 6,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: MOBILE_THEME.colors.ivoryBorder,
    gap: 6,
  },
  itemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  itemName: {
    flex: 1,
    fontSize: 13,
    color: MOBILE_THEME.colors.charcoalInk,
  },
  itemPrice: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  totalRow: {
    marginTop: 6,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: MOBILE_THEME.colors.ivoryBorder,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  totalLabel: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  totalAmount: {
    fontSize: 18,
    fontWeight: "700",
    color: MOBILE_THEME.colors.olivePrimary,
  },
  paymentOptionBox: {
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    gap: 8,
  },
  primaryButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 16,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({ web: { cursor: "pointer" as unknown as undefined } }),
  },
  darkButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 16,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.charcoalInk,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({ web: { cursor: "pointer" as unknown as undefined } }),
  },
  primaryButtonText: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.white,
  },
  secondaryButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 16,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({ web: { cursor: "pointer" as unknown as undefined } }),
  },
  secondaryButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.danger,
  },
  errorCard: {
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.md,
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
    gap: 8,
  },
  errorTitle: {
    flex: 1,
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
});
