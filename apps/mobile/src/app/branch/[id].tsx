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
  Calendar,
  Check,
  Clock,
  MapPin,
  ShieldCheck,
  Star,
  UserCheck,
  WifiOff,
} from "lucide-react-native";
import {
  formatDurationMinutes,
  formatINRFromPaise,
  formatIstTimeSlot,
  type AvailableSlotDto,
} from "@chair/shared-types";
import { formatMobileError, VerifiedDisclaimerFooter } from "@/components/MobileSharedChrome";
import { useMobileApp } from "@/context/MobileAppContext";
import { createSlotHold, makeMobileIdempotencyKey } from "@/services/bookingsApi";
import {
  fetchBranchAvailability,
  fetchBranchDetail,
  formatIstDateKey,
} from "@/services/discoveryApi";
import { MobileApiError } from "@/services/http";
import { MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "@/theme/tokens";

export default function BranchDetailScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const branchId = typeof id === "string" ? id : "";
  const { locale, session, setSession, setProfile, t } = useMobileApp();
  const [holdError, setHoldError] = useState<string | null>(null);
  const holdIdemKeyRef = useRef<string>(makeMobileIdempotencyKey("hold"));

  const [selectedServiceIds, setSelectedServiceIds] = useState<string[]>([]);
  const [selectedStaffId, setSelectedStaffId] = useState<string | null>(null);
  const [selectedDateIso, setSelectedDateIso] = useState<string>(() => formatIstDateKey(0));
  const [selectedSlot, setSelectedSlot] = useState<AvailableSlotDto | null>(null);

  const dateOptions = useMemo(
    () =>
      [0, 1, 2, 3, 4, 5].map((offset) => {
        const iso = formatIstDateKey(offset);
        const dt = new Date(`${iso}T12:00:00+05:30`);
        const label = new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", {
          timeZone: "Asia/Kolkata",
          weekday: "short",
          day: "numeric",
          month: "short",
        }).format(dt);
        return { iso, label };
      }),
    [locale]
  );

  const detailQuery = useQuery({
    queryKey: ["branch-detail", branchId],
    enabled: Boolean(branchId),
    queryFn: () => fetchBranchDetail(branchId),
  });

  const detail = detailQuery.data;
  const initializedBranchRef = useRef<string | null>(null);

  useEffect(() => {
    initializedBranchRef.current = null;
    setSelectedServiceIds([]);
    setSelectedStaffId(null);
    setSelectedSlot(null);
  }, [branchId]);

  // Pre-select the first available service once per branch when branch detail finishes loading.
  useEffect(() => {
    if (
      detail &&
      initializedBranchRef.current !== detail.id &&
      detail.services.length > 0
    ) {
      initializedBranchRef.current = detail.id;
      setSelectedServiceIds([detail.services[0].id]);
    }
  }, [detail]);

  const qualifiedStaff = useMemo(() => {
    if (!detail) {
      return [];
    }
    return detail.staff.filter(
      (barber) =>
        barber.is_accepting_bookings &&
        selectedServiceIds.every((sid) => barber.qualified_branch_service_ids.includes(sid))
    );
  }, [detail, selectedServiceIds]);

  // Clear specific barber selection if current multi-service selection disqualifies them.
  useEffect(() => {
    if (
      selectedStaffId &&
      !qualifiedStaff.some((barber) => barber.id === selectedStaffId)
    ) {
      setSelectedStaffId(null);
    }
  }, [qualifiedStaff, selectedStaffId]);

  useEffect(() => {
    setSelectedSlot(null);
    setHoldError(null);
  }, [selectedServiceIds, selectedDateIso, selectedStaffId]);

  useEffect(() => {
    holdIdemKeyRef.current = makeMobileIdempotencyKey("hold");
  }, [branchId, selectedServiceIds, selectedSlot?.start_at, selectedStaffId]);

  const createHoldMutation = useMutation({
    mutationFn: async (slot: AvailableSlotDto) => {
      if (!session) {
        throw new MobileApiError(401, "AUTHENTICATION_REQUIRED", t.auth.sessionExpired);
      }
      return createSlotHold(
        session,
        {
          branch_id: branchId,
          branch_service_ids: selectedServiceIds,
          start_at: slot.start_at,
          staff_id: selectedStaffId,
        },
        (next) => {
          setSession(next);
          if (!next) {
            setProfile(null);
          }
        },
        holdIdemKeyRef.current
      );
    },
    onSuccess: (createdHold) => {
      setHoldError(null);
      holdIdemKeyRef.current = makeMobileIdempotencyKey("hold");
      void queryClient.invalidateQueries({ queryKey: ["branch-availability"] });
      void queryClient.invalidateQueries({ queryKey: ["mobile-bookings"] });
      router.push({ pathname: "/hold/[id]", params: { id: createdHold.hold_id } });
    },
    onError: (err) => {
      setHoldError(formatMobileError(err, t));
    },
  });

  const availabilityQuery = useQuery({
    queryKey: [
      "branch-availability",
      branchId,
      selectedServiceIds.join(","),
      selectedDateIso,
      selectedStaffId ?? "any",
    ],
    enabled: Boolean(branchId) && selectedServiceIds.length > 0 && Boolean(detail),
    queryFn: () =>
      fetchBranchAvailability(branchId, selectedServiceIds, selectedDateIso, selectedStaffId),
  });

  function toggleService(serviceId: string) {
    setSelectedServiceIds((prev) =>
      prev.includes(serviceId)
        ? prev.filter((item) => item !== serviceId)
        : prev.length < 5
          ? [...prev, serviceId]
          : prev
    );
  }

  function handleBack() {
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace("/(tabs)");
    }
  }

  const selectedServices = useMemo(
    () => (detail ? detail.services.filter((s) => selectedServiceIds.includes(s.id)) : []),
    [detail, selectedServiceIds]
  );
  const totalPricePaise = selectedServices.reduce((acc, s) => acc + s.price_paise, 0);
  const totalDurationMinutes = selectedServices.reduce((acc, s) => acc + s.duration_minutes, 0);
  const staffSlotDuration =
    selectedStaffId && selectedSlot
      ? selectedSlot.available_staff.find((st) => st.staff_id === selectedStaffId)
          ?.duration_minutes
      : undefined;
  const displayDurationMinutes =
    staffSlotDuration ?? selectedSlot?.duration_minutes ?? totalDurationMinutes;

  const detailErr =
    detailQuery.error instanceof MobileApiError ? detailQuery.error : null;
  const availErr =
    availabilityQuery.error instanceof MobileApiError ? availabilityQuery.error : null;

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.topNav}>
        <Pressable
          accessibilityRole="button"
          onPress={handleBack}
          style={styles.backButton}
        >
          <ArrowLeft size={18} color={MOBILE_THEME.colors.charcoalInk} />
          <Text style={styles.backText}>{t.navigation.backToExplore}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.container}>
        {detailQuery.isPending && (
          <View style={styles.card}>
            <View style={styles.rowGapSm}>
              <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
              <Text style={styles.mutedText}>{t.states.loading}</Text>
            </View>
          </View>
        )}

        {!detailQuery.isPending && detailQuery.isError && (
          <View style={styles.errorCard}>
            <View style={styles.rowGapSm}>
              {detailErr?.code === "OFFLINE" ? (
                <WifiOff size={18} color={MOBILE_THEME.colors.bronzeAccent} />
              ) : (
                <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
              )}
              <Text style={styles.errorTitle}>{formatMobileError(detailQuery.error, t)}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              onPress={() => void detailQuery.refetch()}
              style={styles.darkButton}
            >
              <Text style={styles.primaryButtonText}>{t.health.retry}</Text>
            </Pressable>
          </View>
        )}

        {detail && (
          <>
            <View style={styles.card}>
              <Text style={styles.branchTitle}>{detail.name}</Text>
              <View style={styles.rowGapSm}>
                <MapPin size={14} color={MOBILE_THEME.colors.charcoalMuted} />
                <Text style={styles.mutedText}>
                  {detail.address_line1}, {detail.city} - {detail.pincode}
                </Text>
              </View>

              <View style={styles.badgesRow}>
                {detail.verification_status === "CHAIR_VERIFIED" && (
                  <View style={styles.verifiedBadge}>
                    <ShieldCheck size={14} color={MOBILE_THEME.colors.olivePrimary} />
                    <Text style={styles.badgeText}>{t.discovery.verifiedLabel}</Text>
                  </View>
                )}
                {detail.is_featured && (
                  <View style={styles.featuredBadge}>
                    <Text style={styles.badgeText}>
                      {detail.featured_disclosure_label || t.discovery.sponsoredFallback}
                    </Text>
                  </View>
                )}
                <View style={styles.neutralBadge}>
                  <Star size={13} color={MOBILE_THEME.colors.bronzeAccent} />
                  <Text style={styles.badgeText}>
                    {detail.rating_summary.avg_rating != null &&
                    detail.rating_summary.review_count > 0
                      ? `${detail.rating_summary.avg_rating.toFixed(1)} (${detail.rating_summary.review_count})`
                      : t.discovery.newOnChair}
                  </Text>
                </View>
                <View style={styles.neutralBadge}>
                  <Text style={styles.badgeText}>
                    {detail.chair_count} {t.discovery.chairsCountSuffix}
                  </Text>
                </View>
              </View>

              {detail.latest_inspection && (() => {
                const outcome = detail.latest_inspection.overall_outcome;
                const isPassed = outcome === "PASSED";
                const isFailedCritical = outcome === "FAILED_CRITICAL";
                return (
                  <View
                    style={
                      isFailedCritical
                        ? styles.inspectionDangerBox
                        : isPassed
                          ? styles.inspectionPassBox
                          : styles.inspectionWarningBox
                    }
                  >
                    <Text
                      style={
                        isFailedCritical
                          ? styles.inspectionDangerText
                          : isPassed
                            ? styles.inspectionPassText
                            : styles.inspectionWarningText
                      }
                    >
                      {isFailedCritical
                        ? t.branch.inspectionFailedCritical
                        : isPassed
                          ? t.branch.inspectionPassed
                          : t.branch.inspectionActionRequired}
                      {!isFailedCritical && detail.latest_inspection.numerical_score != null
                        ? ` (${detail.latest_inspection.numerical_score}/100)`
                        : ""}
                    </Text>
                  </View>
                );
              })()}
            </View>

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>{t.branch.servicesHeading}</Text>
              {detail.services.map((svc) => {
                const selected = selectedServiceIds.includes(svc.id);
                const label = locale === "hi" ? svc.display_name_hi : svc.display_name_en;
                return (
                  <Pressable
                    key={svc.id}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: selected }}
                    onPress={() => toggleService(svc.id)}
                    style={[styles.serviceRow, selected && styles.serviceRowActive]}
                  >
                    <View style={styles.serviceMeta}>
                      <Text style={styles.serviceTitle}>{label}</Text>
                      <Text style={styles.mutedText}>
                        {formatDurationMinutes(svc.duration_minutes, locale)}
                      </Text>
                    </View>
                    <View style={styles.rowGapSm}>
                      <Text style={styles.servicePrice}>
                        {formatINRFromPaise(svc.price_paise)}
                      </Text>
                      <View style={[styles.checkBox, selected && styles.checkBoxActive]}>
                        {selected && <Check size={14} color={MOBILE_THEME.colors.white} />}
                      </View>
                    </View>
                  </Pressable>
                );
              })}
            </View>

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>{t.branch.barbersHeading}</Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.pillsRow}
              >
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ selected: selectedStaffId === null }}
                  onPress={() => setSelectedStaffId(null)}
                  style={[styles.pill, selectedStaffId === null && styles.pillActive]}
                >
                  <Text
                    style={[styles.pillText, selectedStaffId === null && styles.pillTextActive]}
                  >
                    {t.branch.anyBarberOption}
                  </Text>
                </Pressable>

                {qualifiedStaff.map((barber) => {
                  const active = selectedStaffId === barber.id;
                  return (
                    <Pressable
                      key={barber.id}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}
                      onPress={() => setSelectedStaffId(barber.id)}
                      style={[styles.pill, active && styles.pillActive]}
                    >
                      {barber.is_verified_staff && (
                        <UserCheck
                          size={14}
                          color={active ? MOBILE_THEME.colors.white : MOBILE_THEME.colors.olivePrimary}
                        />
                      )}
                      <Text style={[styles.pillText, active && styles.pillTextActive]}>
                        {barber.display_name}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </View>

            <View style={styles.card}>
              <View style={styles.rowGapSm}>
                <Calendar size={16} color={MOBILE_THEME.colors.olivePrimary} />
                <Text style={styles.sectionTitle}>{t.branch.selectDateHeading}</Text>
              </View>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.pillsRow}
              >
                {dateOptions.map((opt) => {
                  const active = selectedDateIso === opt.iso;
                  return (
                    <Pressable
                      key={opt.iso}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}
                      onPress={() => setSelectedDateIso(opt.iso)}
                      style={[styles.pill, active && styles.pillActive]}
                    >
                      <Text style={[styles.pillText, active && styles.pillTextActive]}>
                        {opt.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              <Text style={styles.sectionTitle}>{t.branch.slotsHeading}</Text>

              {selectedServiceIds.length === 0 ? (
                <Text style={styles.mutedText}>{t.branch.selectServicesPrompt}</Text>
              ) : availabilityQuery.isPending ? (
                <View style={styles.rowGapSm}>
                  <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
                  <Text style={styles.mutedText}>{t.states.loading}</Text>
                </View>
              ) : availabilityQuery.isError ? (
                <View style={styles.errorCard}>
                  <View style={styles.rowGapSm}>
                    {availErr?.code === "OFFLINE" ? (
                      <WifiOff size={18} color={MOBILE_THEME.colors.bronzeAccent} />
                    ) : (
                      <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
                    )}
                    <Text style={styles.errorTitle}>
                      {formatMobileError(availabilityQuery.error, t)}
                    </Text>
                  </View>
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => void availabilityQuery.refetch()}
                    style={styles.darkButton}
                  >
                    <Text style={styles.primaryButtonText}>{t.health.retry}</Text>
                  </Pressable>
                </View>
              ) : availabilityQuery.data?.online_booking_paused ? (
                <Text style={styles.pausedText}>{t.branch.pausedNotice}</Text>
              ) : availabilityQuery.data?.is_branch_closed ? (
                <Text style={styles.mutedText}>{t.branch.closedNotice}</Text>
              ) : (availabilityQuery.data?.slots.length ?? 0) === 0 ? (
                <Text style={styles.mutedText}>{t.branch.noSlotsNotice}</Text>
              ) : (
                <View style={styles.slotGrid}>
                  {availabilityQuery.data?.slots.map((slot) => {
                    const isSelected = selectedSlot?.start_at === slot.start_at;
                    const timeLabel = formatIstTimeSlot(slot.start_at, locale);
                    return (
                      <Pressable
                        key={slot.start_at}
                        accessibilityRole="button"
                        accessibilityState={{ selected: isSelected }}
                        onPress={() => setSelectedSlot(slot)}
                        style={[styles.slotButton, isSelected && styles.slotButtonActive]}
                      >
                        <Clock
                          size={13}
                          color={
                            isSelected ? MOBILE_THEME.colors.white : MOBILE_THEME.colors.olivePrimary
                          }
                        />
                        <Text
                          style={[
                            styles.slotButtonText,
                            isSelected && styles.slotButtonTextActive,
                          ]}
                        >
                          {timeLabel}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              )}
            </View>

            {selectedServices.length > 0 && (
              <View style={styles.summaryCard}>
                <View style={styles.summaryHeader}>
                  <Text style={styles.sectionTitle}>{t.branch.selectedSummaryTitle}</Text>
                  {selectedSlot && (
                    <Pressable
                      accessibilityRole="button"
                      onPress={() => setSelectedSlot(null)}
                      style={styles.clearButton}
                    >
                      <Text style={styles.clearButtonText}>{t.branch.clearSelection}</Text>
                    </Pressable>
                  )}
                </View>
                <Text style={styles.summaryMeta}>
                  {selectedServices.length} {t.branch.selectedServicesCount} ·{" "}
                  {t.branch.totalDurationLabel}:{" "}
                  {formatDurationMinutes(displayDurationMinutes, locale)} ·{" "}
                  {t.branch.totalPriceLabel}: {formatINRFromPaise(totalPricePaise)}
                </Text>
                {selectedSlot && (
                  <Text style={styles.selectedTimeText}>
                    {t.branch.slotTimeLabel}: {formatIstTimeSlot(selectedSlot.start_at, locale)} (
                    {selectedSlot.available_staff.map((st) => st.display_name).join(", ")})
                  </Text>
                )}
                {holdError && (
                  <View style={styles.errorCard}>
                    <Text style={styles.errorTitle}>{holdError}</Text>
                  </View>
                )}
                {selectedSlot && session ? (
                  <Pressable
                    accessibilityRole="button"
                    disabled={createHoldMutation.isPending}
                    onPress={() => createHoldMutation.mutate(selectedSlot)}
                    style={styles.holdPrimaryButton}
                  >
                    <Text style={styles.primaryButtonText}>
                      {createHoldMutation.isPending
                        ? t.branch.lockingHold
                        : t.branch.holdAndCheckoutCta}
                    </Text>
                  </Pressable>
                ) : !session ? (
                  <View style={styles.accountPromptRow}>
                    <Text style={styles.mutedText}>{t.branch.signInToSaveHint}</Text>
                    <Pressable
                      accessibilityRole="button"
                      onPress={() => router.push("/(tabs)/account")}
                      style={styles.secondaryButton}
                    >
                      <Text style={styles.secondaryButtonText}>
                        {selectedSlot ? t.branch.signInToHoldCta : t.branch.openAccountButton}
                      </Text>
                    </Pressable>
                  </View>
                ) : null}
              </View>
            )}

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>{t.branch.reviewsHeading}</Text>
              {detail.rating_summary.recent_reviews.length === 0 ? (
                <Text style={styles.mutedText}>{t.branch.noReviewsYet}</Text>
              ) : (
                detail.rating_summary.recent_reviews.map((rev) => (
                  <View key={rev.id} style={styles.reviewItem}>
                    <Text style={styles.serviceTitle}>
                      {rev.rating}/5 · {t.branch.hygieneRatingLabel} {rev.hygiene_rating}/5
                    </Text>
                    {rev.comment ? <Text style={styles.mutedText}>{rev.comment}</Text> : null}
                  </View>
                ))
              )}
            </View>

            <VerifiedDisclaimerFooter disclaimerText={detail.verification_badge_disclaimer} />
          </>
        )}
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
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
  },
  backButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    alignSelf: "flex-start",
    paddingRight: 12,
    ...Platform.select({
      web: { cursor: "pointer" as unknown as undefined },
    }),
  },
  backText: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  container: {
    padding: MOBILE_THEME.spacing.lg,
    gap: MOBILE_THEME.spacing.md,
  },
  card: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    gap: MOBILE_THEME.spacing.sm,
  },
  branchTitle: {
    fontSize: 22,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  rowGapSm: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  mutedText: {
    fontSize: 13,
    lineHeight: 19,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  badgesRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: MOBILE_THEME.spacing.xs,
    marginTop: 4,
  },
  verifiedBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
  },
  featuredBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
  },
  neutralBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  inspectionPassBox: {
    alignSelf: "flex-start",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
  },
  inspectionWarningBox: {
    alignSelf: "flex-start",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
  },
  inspectionDangerBox: {
    alignSelf: "flex-start",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
  },
  inspectionPassText: {
    fontSize: 12,
    fontWeight: "600",
    color: MOBILE_THEME.colors.olivePrimary,
  },
  inspectionWarningText: {
    fontSize: 12,
    fontWeight: "600",
    color: MOBILE_THEME.colors.bronzeAccent,
  },
  inspectionDangerText: {
    fontSize: 12,
    fontWeight: "700",
    color: MOBILE_THEME.colors.danger,
  },
  serviceRow: {
    minHeight: TOUCH_TARGET_MIN_DP,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    gap: MOBILE_THEME.spacing.md,
  },
  serviceRowActive: {
    borderColor: MOBILE_THEME.colors.olivePrimary,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
  },
  serviceMeta: {
    flex: 1,
  },
  serviceTitle: {
    fontSize: 15,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  servicePrice: {
    fontSize: 15,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  checkBox: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.white,
    alignItems: "center",
    justifyContent: "center",
  },
  checkBoxActive: {
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  pillsRow: {
    gap: MOBILE_THEME.spacing.sm,
    paddingVertical: 2,
  },
  pill: {
    minHeight: TOUCH_TARGET_MIN_DP,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    borderRadius: MOBILE_THEME.radii.pill,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
  },
  pillActive: {
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  pillText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  pillTextActive: {
    color: MOBILE_THEME.colors.white,
  },
  slotGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: MOBILE_THEME.spacing.sm,
  },
  slotButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    minWidth: 100,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 12,
    borderRadius: MOBILE_THEME.radii.sm,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
    ...Platform.select({
      web: { cursor: "pointer" as unknown as undefined },
    }),
  },
  slotButtonActive: {
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  slotButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  slotButtonTextActive: {
    color: MOBILE_THEME.colors.white,
  },
  pausedText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.danger,
  },
  summaryCard: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.olivePrimary,
    backgroundColor: MOBILE_THEME.colors.oliveSoft,
    gap: MOBILE_THEME.spacing.sm,
  },
  summaryHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  summaryMeta: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  selectedTimeText: {
    fontSize: 14,
    fontWeight: "700",
    color: MOBILE_THEME.colors.olivePrimary,
  },
  clearButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 10,
    justifyContent: "center",
  },
  clearButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  accountPromptRow: {
    marginTop: 4,
    gap: MOBILE_THEME.spacing.sm,
  },
  reviewItem: {
    paddingTop: MOBILE_THEME.spacing.xs,
    borderTopWidth: 1,
    borderTopColor: MOBILE_THEME.colors.ivoryBorder,
  },
  errorCard: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
    gap: MOBILE_THEME.spacing.sm,
  },
  errorTitle: {
    fontSize: 14,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  darkButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 16,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.charcoalInk,
    alignSelf: "flex-start",
    alignItems: "center",
    justifyContent: "center",
  },
  primaryButtonText: {
    fontSize: 13,
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
    alignSelf: "flex-start",
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  holdPrimaryButton: {
    marginTop: 6,
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
});
