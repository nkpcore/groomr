import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { FlashList } from "@shopify/flash-list";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFocusEffect, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  KeyRound,
  Lock,
  Star,
  WifiOff,
} from "lucide-react-native";
import {
  formatDurationMinutes,
  formatINRFromPaise,
  formatIstDateTime,
  type BookingDetailDto,
  type BookingStatus,
} from "@chair/shared-types";
import {
  LanguageSwitcher,
  VerifiedDisclaimerFooter,
  formatMobileError,
} from "@/components/MobileSharedChrome";
import { useMobileApp } from "@/context/MobileAppContext";
import {
  cancelMyBooking,
  fetchMyBookings,
  makeMobileIdempotencyKey,
  submitBookingReview,
} from "@/services/bookingsApi";
import { MobileApiError } from "@/services/http";
import { MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "@/theme/tokens";

function getBookingStatusLabel(
  status: BookingStatus,
  t: ReturnType<typeof useMobileApp>["t"]
): string {
  const map: Record<BookingStatus, string> = {
    HELD: t.bookings.statusHELD,
    REQUESTED: t.bookings.statusREQUESTED,
    CONFIRMED: t.bookings.statusCONFIRMED,
    CHECKED_IN: t.bookings.statusCHECKED_IN,
    IN_SERVICE: t.bookings.statusIN_SERVICE,
    COMPLETED: t.bookings.statusCOMPLETED,
    CANCELLED: t.bookings.statusCANCELLED,
    EXPIRED: t.bookings.statusEXPIRED,
    NO_SHOW: t.bookings.statusNO_SHOW,
  };
  return map[status] ?? status;
}

function getPaymentStatusLabel(
  status: string,
  t: ReturnType<typeof useMobileApp>["t"]
): string {
  const map: Record<string, string> = {
    PENDING: t.bookings.payStatusPENDING,
    AUTHORIZED: t.bookings.payStatusAUTHORIZED,
    CAPTURED: t.bookings.payStatusCAPTURED,
    FAILED: t.bookings.payStatusFAILED,
    REFUND_PENDING: t.bookings.payStatusREFUND_PENDING,
    REFUNDED: t.bookings.payStatusREFUNDED,
    PAY_AT_SALON: t.bookings.payStatusPAY_AT_SALON,
  };
  return map[status] ?? status;
}

function getRefundStatusLabel(
  status: string,
  t: ReturnType<typeof useMobileApp>["t"]
): string {
  const map: Record<string, string> = {
    PENDING: t.bookings.refundStatusPENDING,
    PROCESSED: t.bookings.refundStatusPROCESSED,
    FAILED: t.bookings.refundStatusFAILED,
  };
  return map[status] ?? status;
}

export default function MobileBookingsScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { locale, setLocale, session, setSession, setProfile, sessionHydrating, t } =
    useMobileApp();

  const [reviewDraft, setReviewDraft] = useState<
    Record<string, { rating: number; hygiene: number; comment: string }>
  >({});
  const [statusNotice, setStatusNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleSessionUpdate = useCallback(
    (next: typeof session) => {
      setSession(next);
      if (!next) {
        setProfile(null);
      }
    },
    [setProfile, setSession]
  );

  const bookingsQuery = useQuery({
    queryKey: ["mobile-bookings", session?.userId ?? "anon"],
    enabled: Boolean(session),
    queryFn: () => fetchMyBookings(session!, handleSessionUpdate),
  });
  const { refetch: refetchBookings } = bookingsQuery;

  useFocusEffect(
    useCallback(() => {
      if (session) {
        void refetchBookings();
      }
    }, [refetchBookings, session])
  );

  const cancelMutation = useMutation({
    mutationFn: async (bookingId: string) => {
      if (!session) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      return cancelMyBooking(
        session,
        bookingId,
        null,
        handleSessionUpdate,
        makeMobileIdempotencyKey(`cancel-${bookingId}`)
      );
    },
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["mobile-bookings"] });
      void queryClient.invalidateQueries({ queryKey: ["branch-availability"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-branches"] });
    },
    onError: (err) => {
      setActionError(formatMobileError(err, t));
    },
  });

  const reviewMutation = useMutation({
    mutationFn: async ({
      bookingId,
      rating,
      hygiene,
      comment,
    }: {
      bookingId: string;
      rating: number;
      hygiene: number;
      comment: string;
    }) => {
      if (!session) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      return submitBookingReview(
        session,
        bookingId,
        { rating, hygiene_rating: hygiene, comment: comment.trim() || null },
        handleSessionUpdate
      );
    },
    onSuccess: () => {
      setActionError(null);
      setStatusNotice(t.bookings.reviewSubmitted);
      void queryClient.invalidateQueries({ queryKey: ["mobile-bookings"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-branches"] });
    },
    onError: (err) => {
      setActionError(formatMobileError(err, t));
    },
  });

  const items = bookingsQuery.data?.items ?? [];
  const queryErr = bookingsQuery.error instanceof MobileApiError ? bookingsQuery.error : null;

  const headerElement = (
    <View style={styles.headerBlock}>
      <View style={styles.topRow}>
        <View style={styles.titleWrap}>
          <Text style={styles.titleText}>{t.bookings.heading}</Text>
          <Text style={styles.mutedText}>{t.bookings.subtitle}</Text>
        </View>
        <LanguageSwitcher locale={locale} onChange={setLocale} />
      </View>

      {statusNotice && (
        <View style={styles.noticeBox}>
          <CheckCircle2 size={18} color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.noticeText}>{statusNotice}</Text>
        </View>
      )}

      {actionError && (
        <View style={styles.errorCard}>
          <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
          <Text style={styles.errorTitle}>{actionError}</Text>
        </View>
      )}

      {sessionHydrating && (
        <View style={styles.stateCard}>
          <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.mutedText}>{t.states.loading}</Text>
        </View>
      )}

      {!sessionHydrating && !session && (
        <View style={styles.stateCard}>
          <Lock size={20} color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.cardTitle}>{t.bookings.signInRequired}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => router.push("/(tabs)/account")}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>{t.branch.openAccountButton}</Text>
          </Pressable>
        </View>
      )}

      {session && bookingsQuery.isPending && (
        <View style={styles.stateCard}>
          <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.mutedText}>{t.states.loading}</Text>
        </View>
      )}

      {session && !bookingsQuery.isPending && bookingsQuery.isError && (
        <View style={styles.errorCard}>
          {queryErr?.code === "OFFLINE" ? (
            <WifiOff size={18} color={MOBILE_THEME.colors.bronzeAccent} />
          ) : (
            <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
          )}
          <Text style={styles.errorTitle}>{formatMobileError(bookingsQuery.error, t)}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => void bookingsQuery.refetch()}
            style={styles.darkButton}
          >
            <Text style={styles.primaryButtonText}>{t.health.retry}</Text>
          </Pressable>
        </View>
      )}

      {session && !bookingsQuery.isPending && !bookingsQuery.isError && items.length === 0 && (
        <View style={styles.stateCard}>
          <Calendar size={20} color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.cardTitle}>{t.bookings.emptyHeading}</Text>
          <Text style={styles.mutedText}>{t.bookings.emptySubtitle}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => router.push("/(tabs)")}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>{t.bookings.browseSalonsCta}</Text>
          </Pressable>
        </View>
      )}
    </View>
  );

  const renderItem = useCallback(
    ({ item }: { item: BookingDetailDto }) => {
      const canFinishHold = item.status === "HELD" && item.slot_hold_id;
      const canCancel =
        item.status === "HELD" || item.status === "REQUESTED" || item.status === "CONFIRMED";
      const canReview = item.status === "COMPLETED" && !item.has_review;
      const draft = reviewDraft[item.id] ?? { rating: 5, hygiene: 5, comment: "" };

      return (
        <View style={styles.bookingCard}>
          <View style={styles.cardTopRow}>
            <View style={styles.titleWrap}>
              <Text style={styles.cardTitle}>{item.branch_name}</Text>
              <Text style={styles.mutedText}>
                {t.bookings.bookingCodeLabel}: {item.booking_code}
              </Text>
            </View>
            <View
              style={[
                styles.statusBadge,
                item.status === "CONFIRMED" || item.status === "COMPLETED"
                  ? styles.statusPositive
                  : item.status === "CANCELLED" || item.status === "EXPIRED"
                    ? styles.statusDanger
                    : styles.statusNeutral,
              ]}
            >
              <Text style={styles.statusText}>{getBookingStatusLabel(item.status, t)}</Text>
            </View>
          </View>

          <Text style={styles.metaText}>
            {formatIstDateTime(item.scheduled_start_at, locale)}
            {item.staff_name ? ` · ${item.staff_name}` : ""}
            {item.resource_name ? ` · ${item.resource_name}` : ""}
          </Text>

          <Text style={styles.mutedText}>
            {item.items
              .map(
                (sv) =>
                  `${sv.service_name_snapshot} (${formatDurationMinutes(
                    sv.duration_minutes_snapshot,
                    locale
                  )})`
              )
              .join(" · ")}
          </Text>

          <View style={styles.priceRow}>
            <Text style={styles.priceText}>{formatINRFromPaise(item.net_payable_paise)}</Text>
            {item.payment && (
              <Text style={styles.mutedText}>
                {t.bookings.paymentStatusLabel}: {getPaymentStatusLabel(item.payment.status, t)}
              </Text>
            )}
          </View>

          {item.check_in_otp && (
            <View style={styles.otpBox}>
              <KeyRound size={16} color={MOBILE_THEME.colors.olivePrimary} />
              <Text style={styles.otpText}>
                {t.bookings.checkInOtpLabel}: {item.check_in_otp}
              </Text>
            </View>
          )}

          {item.completion_otp && (
            <View style={styles.otpBox}>
              <KeyRound size={16} color={MOBILE_THEME.colors.bronzeAccent} />
              <Text style={styles.otpText}>
                {t.bookings.completionOtpLabel}: {item.completion_otp}
              </Text>
            </View>
          )}

          {item.refund && (
            <View style={styles.refundBadge}>
              <Text style={styles.metaText}>
                {t.bookings.refundBadge}: {formatINRFromPaise(item.refund.amount_paise)} (
                {getRefundStatusLabel(item.refund.status, t)})
              </Text>
            </View>
          )}

          <View style={styles.actionsRow}>
            {canFinishHold && item.slot_hold_id && (
              <Pressable
                accessibilityRole="button"
                onPress={() =>
                  router.push({ pathname: "/hold/[id]", params: { id: item.slot_hold_id! } })
                }
                style={styles.primaryButton}
              >
                <Text style={styles.primaryButtonText}>{t.checkout.heading}</Text>
              </Pressable>
            )}

            {canCancel && (
              <Pressable
                accessibilityRole="button"
                disabled={cancelMutation.isPending}
                onPress={() => cancelMutation.mutate(item.id)}
                style={styles.secondaryButton}
              >
                <Text style={styles.cancelText}>
                  {cancelMutation.isPending ? t.bookings.cancelling : t.bookings.cancelBookingCta}
                </Text>
              </Pressable>
            )}
          </View>

          {item.has_review && (
            <View style={styles.otpBox}>
              <Star size={14} color={MOBILE_THEME.colors.bronzeAccent} />
              <Text style={styles.metaText}>{t.bookings.reviewedBadge}</Text>
            </View>
          )}

          {canReview && (
            <View style={styles.reviewBox}>
              <Text style={styles.metaText}>{t.bookings.reviewHeading}</Text>

              <Text style={styles.mutedText}>{t.bookings.overallRatingLabel}</Text>
              <View style={styles.ratingRow}>
                {[1, 2, 3, 4, 5].map((score) => (
                  <Pressable
                    key={`r-${score}`}
                    accessibilityRole="button"
                    accessibilityState={{ selected: draft.rating === score }}
                    onPress={() =>
                      setReviewDraft((prev) => ({
                        ...prev,
                        [item.id]: { ...draft, rating: score },
                      }))
                    }
                    style={[
                      styles.scoreChip,
                      draft.rating === score && styles.scoreChipActive,
                    ]}
                  >
                    <Text
                      style={[
                        styles.scoreChipText,
                        draft.rating === score && styles.scoreChipTextActive,
                      ]}
                    >
                      {score}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.mutedText}>{t.bookings.hygieneRatingLabel}</Text>
              <View style={styles.ratingRow}>
                {[1, 2, 3, 4, 5].map((score) => (
                  <Pressable
                    key={`h-${score}`}
                    accessibilityRole="button"
                    accessibilityState={{ selected: draft.hygiene === score }}
                    onPress={() =>
                      setReviewDraft((prev) => ({
                        ...prev,
                        [item.id]: { ...draft, hygiene: score },
                      }))
                    }
                    style={[
                      styles.scoreChip,
                      draft.hygiene === score && styles.scoreChipActive,
                    ]}
                  >
                    <Text
                      style={[
                        styles.scoreChipText,
                        draft.hygiene === score && styles.scoreChipTextActive,
                      ]}
                    >
                      {score}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <TextInput
                value={draft.comment}
                onChangeText={(txt) =>
                  setReviewDraft((prev) => ({
                    ...prev,
                    [item.id]: { ...draft, comment: txt },
                  }))
                }
                placeholder={t.bookings.commentPlaceholder}
                placeholderTextColor={MOBILE_THEME.colors.charcoalMuted}
                style={styles.commentInput}
              />

              <Pressable
                accessibilityRole="button"
                disabled={reviewMutation.isPending}
                onPress={() =>
                  reviewMutation.mutate({
                    bookingId: item.id,
                    rating: draft.rating,
                    hygiene: draft.hygiene,
                    comment: draft.comment,
                  })
                }
                style={styles.primaryButton}
              >
                <Text style={styles.primaryButtonText}>
                  {reviewMutation.isPending
                    ? t.bookings.submittingReview
                    : t.bookings.submitReviewCta}
                </Text>
              </Pressable>
            </View>
          )}
        </View>
      );
    },
    [cancelMutation, locale, reviewDraft, reviewMutation, router, t]
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      <FlashList
        data={session ? items : []}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        estimatedItemSize={220}
        ListHeaderComponent={headerElement}
        ListFooterComponent={
          <VerifiedDisclaimerFooter
            disclaimerText={`${t.brand.verifiedBadge}: ${t.brand.verifiedDisclaimer}`}
          />
        }
        contentContainerStyle={styles.listContent}
        refreshing={bookingsQuery.isRefetching}
        onRefresh={() => {
          if (session) {
            void bookingsQuery.refetch();
          }
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
  },
  listContent: {
    padding: MOBILE_THEME.spacing.lg,
    paddingBottom: MOBILE_THEME.spacing.xl,
  },
  headerBlock: {
    gap: MOBILE_THEME.spacing.md,
    marginBottom: MOBILE_THEME.spacing.md,
  },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: MOBILE_THEME.spacing.md,
  },
  titleWrap: {
    flex: 1,
  },
  titleText: {
    fontSize: 22,
    fontWeight: "600",
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
  stateCard: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
  },
  noticeBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  noticeText: {
    flex: 1,
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  errorCard: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.md,
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
  },
  errorTitle: {
    flex: 1,
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  bookingCard: {
    marginBottom: MOBILE_THEME.spacing.md,
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    gap: MOBILE_THEME.spacing.sm,
  },
  cardTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: MOBILE_THEME.radii.pill,
  },
  statusPositive: {
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
  },
  statusDanger: {
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
  },
  statusNeutral: {
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
  },
  statusText: {
    fontSize: 12,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  priceRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 2,
  },
  priceText: {
    fontSize: 16,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  otpBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
  },
  otpText: {
    flex: 1,
    fontSize: 14,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  refundBadge: {
    padding: MOBILE_THEME.spacing.sm,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
  },
  actionsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: MOBILE_THEME.spacing.sm,
    marginTop: 4,
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
    fontSize: 13,
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
  cancelText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.danger,
  },
  reviewBox: {
    marginTop: 6,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: MOBILE_THEME.colors.ivoryBorder,
    gap: 8,
  },
  ratingRow: {
    flexDirection: "row",
    gap: 8,
  },
  scoreChip: {
    minWidth: TOUCH_TARGET_MIN_DP,
    minHeight: TOUCH_TARGET_MIN_DP,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({ web: { cursor: "pointer" as unknown as undefined } }),
  },
  scoreChipActive: {
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  scoreChipText: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  scoreChipTextActive: {
    color: MOBILE_THEME.colors.white,
  },
  commentInput: {
    minHeight: TOUCH_TARGET_MIN_DP,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.white,
    paddingHorizontal: 12,
    fontSize: 14,
    color: MOBILE_THEME.colors.charcoalInk,
  },
});
