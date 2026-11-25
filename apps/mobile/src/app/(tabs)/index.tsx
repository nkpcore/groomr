import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as Location from "expo-location";
import { FlashList } from "@shopify/flash-list";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AlertCircle,
  Clock,
  Lock,
  MapPin,
  Navigation,
  Search,
  ShieldCheck,
  Star,
  WifiOff,
} from "lucide-react-native";
import {
  formatDistanceMeters,
  formatINRFromPaise,
  formatIstTimeSlot,
  type BranchDiscoveryItemDto,
  type ServiceCategory,
} from "@chair/shared-types";
import {
  LanguageSwitcher,
  VerifiedDisclaimerFooter,
  formatMobileError,
} from "@/components/MobileSharedChrome";
import { useMobileApp } from "@/context/MobileAppContext";
import { fetchBranches, type BranchSearchParams } from "@/services/discoveryApi";
import { MobileApiError } from "@/services/http";
import { MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "@/theme/tokens";

type PresetLocationKey = "all" | "blr" | "mum" | "gps";
type SortModeKey = "default" | "distance" | "price_asc";
type FilterChipKey =
  | "all"
  | "verified"
  | "HAIRCUT"
  | "BEARD"
  | "SHAVE"
  | "under500"
  | "open_now";

const LOCATION_PRESETS: Record<"blr" | "mum", { lat: number; lng: number }> = {
  blr: { lat: 12.9784, lng: 77.6408 },
  mum: { lat: 19.0607, lng: 72.8295 },
};

export default function MobileExploreScreen() {
  const router = useRouter();
  const { locale, setLocale, t } = useMobileApp();

  const [locationPreset, setLocationPreset] = useState<PresetLocationKey>("all");
  const [gpsCoords, setGpsCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locationDenied, setLocationDenied] = useState(false);
  const [gpsError, setGpsError] = useState(false);

  const [searchText, setSearchText] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterChipKey>("all");
  const [sortBy, setSortBy] = useState<SortModeKey>("default");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchText.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchText]);

  const queryParams = useMemo<BranchSearchParams>(() => {
    const coords =
      locationPreset === "gps" && gpsCoords
        ? gpsCoords
        : locationPreset === "blr"
          ? LOCATION_PRESETS.blr
          : locationPreset === "mum"
            ? LOCATION_PRESETS.mum
            : null;

    const category: ServiceCategory | null =
      activeFilter === "HAIRCUT" || activeFilter === "BEARD" || activeFilter === "SHAVE"
        ? activeFilter
        : null;

    return {
      lat: coords?.lat ?? null,
      lng: coords?.lng ?? null,
      radiusMeters: 15_000,
      q: debouncedQuery || null,
      category,
      verifiedOnly: activeFilter === "verified",
      maxPricePaise: activeFilter === "under500" ? 50_000 : null,
      openNow: activeFilter === "open_now",
      sort: sortBy === "default" ? (coords ? "distance" : "featured") : sortBy,
      limit: 25,
    };
  }, [activeFilter, debouncedQuery, gpsCoords, locationPreset, sortBy]);

  const branchesQuery = useQuery({
    queryKey: ["mobile-branches", queryParams],
    queryFn: () => fetchBranches(queryParams),
  });

  const handleUseGps = useCallback(async () => {
    setLocationDenied(false);
    setGpsError(false);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        setLocationDenied(true);
        return;
      }
      const pos = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setGpsCoords({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
      });
      setLocationPreset("gps");
    } catch {
      setGpsError(true);
    }
  }, []);

  const clearAllFilters = useCallback(() => {
    setSearchText("");
    setDebouncedQuery("");
    setActiveFilter("all");
    setLocationPreset("all");
    setSortBy("default");
    setLocationDenied(false);
    setGpsError(false);
  }, []);

  const filterChips: Array<{ key: FilterChipKey; label: string }> = [
    { key: "all", label: t.discovery.filterAll },
    { key: "verified", label: t.discovery.filterVerified },
    { key: "HAIRCUT", label: t.discovery.filterHaircut },
    { key: "BEARD", label: t.discovery.filterBeard },
    { key: "SHAVE", label: t.discovery.filterShave },
    { key: "under500", label: t.discovery.filterUnder500 },
    { key: "open_now", label: t.discovery.filterOpenNow },
  ];

  const items = branchesQuery.data?.items ?? [];
  const apiErr =
    branchesQuery.error instanceof MobileApiError ? branchesQuery.error : null;
  const isOffline = apiErr?.code === "OFFLINE";

  const headerElement = (
    <View style={styles.listHeader}>
      <View style={styles.topRow}>
        <View style={styles.titleBlock}>
          <Text style={styles.brandMark}>{t.brand.name}</Text>
          <Text style={styles.headingText}>{t.discovery.heading}</Text>
          <Text style={styles.subtitleText}>{t.discovery.subtitle}</Text>
        </View>

        <LanguageSwitcher locale={locale} onChange={setLocale} />
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.pillsRow}
      >
        {(
          [
            { key: "all", label: t.discovery.cityAll },
            { key: "blr", label: t.discovery.cityBengaluru },
            { key: "mum", label: t.discovery.cityMumbai },
          ] as const
        ).map((preset) => {
          const selected = locationPreset === preset.key;
          return (
            <Pressable
              key={preset.key}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => {
                setLocationDenied(false);
                setGpsError(false);
                setLocationPreset(preset.key);
              }}
              style={[styles.chipButton, selected && styles.chipButtonActive]}
            >
              <MapPin
                size={14}
                color={selected ? MOBILE_THEME.colors.white : MOBILE_THEME.colors.olivePrimary}
              />
              <Text style={[styles.chipText, selected && styles.chipTextActive]}>
                {preset.label}
              </Text>
            </Pressable>
          );
        })}

        <Pressable
          accessibilityRole="button"
          accessibilityState={{ selected: locationPreset === "gps" }}
          onPress={() => void handleUseGps()}
          style={[styles.chipButton, locationPreset === "gps" && styles.chipButtonActive]}
        >
          <Navigation
            size={14}
            color={
              locationPreset === "gps"
                ? MOBILE_THEME.colors.white
                : MOBILE_THEME.colors.bronzeAccent
            }
          />
          <Text
            style={[styles.chipText, locationPreset === "gps" && styles.chipTextActive]}
          >
            {t.discovery.useGpsLocation}
          </Text>
        </Pressable>
      </ScrollView>

      {locationDenied && (
        <View style={styles.permissionBanner}>
          <Lock size={16} color={MOBILE_THEME.colors.danger} />
          <Text style={styles.permissionText}>{t.discovery.locationDeniedHint}</Text>
        </View>
      )}

      {gpsError && !locationDenied && (
        <View style={styles.gpsErrorBanner}>
          <AlertCircle size={16} color={MOBILE_THEME.colors.bronzeAccent} />
          <Text style={styles.permissionText}>{t.states.error}</Text>
        </View>
      )}

      <View style={styles.searchBar}>
        <Search size={18} color={MOBILE_THEME.colors.charcoalMuted} />
        <TextInput
          value={searchText}
          onChangeText={setSearchText}
          placeholder={t.discovery.searchPlaceholder}
          placeholderTextColor={MOBILE_THEME.colors.charcoalMuted}
          style={styles.searchInput}
          returnKeyType="search"
          accessibilityLabel={t.discovery.searchPlaceholder}
        />
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.pillsRow}
      >
        {filterChips.map((chip) => {
          const selected = activeFilter === chip.key;
          return (
            <Pressable
              key={chip.key}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => setActiveFilter(chip.key)}
              style={[styles.chipButton, selected && styles.chipButtonActive]}
            >
              <Text style={[styles.chipText, selected && styles.chipTextActive]}>
                {chip.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.pillsRow}
      >
        {(
          [
            { key: "distance", label: t.discovery.sortDistance },
            { key: "price_asc", label: t.discovery.sortPrice },
          ] as const
        ).map((opt) => {
          const selected = sortBy === opt.key;
          return (
            <Pressable
              key={opt.key}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => setSortBy((prev) => (prev === opt.key ? "default" : opt.key))}
              style={[styles.chipButton, selected && styles.chipButtonActive]}
            >
              <Text style={[styles.chipText, selected && styles.chipTextActive]}>
                {opt.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {branchesQuery.isPending && (
        <View style={styles.stateCard}>
          <ActivityIndicator color={MOBILE_THEME.colors.olivePrimary} />
          <Text style={styles.stateText}>{t.states.loading}</Text>
        </View>
      )}

      {!branchesQuery.isPending && branchesQuery.isError && (
        <View style={styles.errorCard}>
          <View style={styles.rowGapSm}>
            {isOffline ? (
              <WifiOff size={18} color={MOBILE_THEME.colors.bronzeAccent} />
            ) : (
              <AlertCircle size={18} color={MOBILE_THEME.colors.danger} />
            )}
            <Text style={styles.errorTitle}>
              {formatMobileError(branchesQuery.error, t)}
            </Text>
          </View>
          <Pressable
            accessibilityRole="button"
            onPress={() => void branchesQuery.refetch()}
            style={styles.retryButton}
          >
            <Text style={styles.retryText}>{t.health.retry}</Text>
          </Pressable>
        </View>
      )}

      {!branchesQuery.isPending && !branchesQuery.isError && items.length === 0 && (
        <View style={styles.stateCard}>
          <Text style={styles.cardTitle}>{t.discovery.emptyResults}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={clearAllFilters}
            style={styles.secondaryButton}
          >
            <Text style={styles.secondaryButtonText}>{t.discovery.clearFilters}</Text>
          </Pressable>
        </View>
      )}
    </View>
  );

  const renderItem = useCallback(
    ({ item }: { item: BranchDiscoveryItemDto }) => {
      const distanceLabel = formatDistanceMeters(item.distance_meters, locale);
      const isVerified = item.verification_status === "CHAIR_VERIFIED";
      const startingPrice =
        item.starting_price_paise != null ? formatINRFromPaise(item.starting_price_paise) : null;

      return (
        <Pressable
          accessibilityRole="button"
          onPress={() => router.push({ pathname: "/branch/[id]", params: { id: item.id } })}
          style={styles.branchCard}
        >
          <View style={styles.cardHeaderRow}>
            <View style={styles.titleBlock}>
              <Text style={styles.cardTitle}>{item.name}</Text>
              <Text style={styles.mutedText}>
                {item.address_line1} · {item.city}
                {distanceLabel ? ` · ${distanceLabel}` : ""}
              </Text>
            </View>
            {startingPrice && (
              <View style={styles.priceBadge}>
                <Text style={styles.priceCaption}>{t.discovery.startingAtPrefix}</Text>
                <Text style={styles.priceValue}>{startingPrice}</Text>
              </View>
            )}
          </View>

          <View style={styles.badgesRow}>
            {isVerified && (
              <View style={styles.verifiedBadge}>
                <ShieldCheck size={13} color={MOBILE_THEME.colors.olivePrimary} />
                <Text style={styles.verifiedBadgeText}>{t.discovery.verifiedLabel}</Text>
              </View>
            )}
            {item.is_featured && (
              <View style={styles.featuredBadge}>
                <Text style={styles.featuredBadgeText}>
                  {item.featured_disclosure_label || t.discovery.sponsoredFallback}
                </Text>
              </View>
            )}
            <View style={styles.neutralBadge}>
              <Star size={12} color={MOBILE_THEME.colors.bronzeAccent} />
              <Text style={styles.neutralBadgeText}>
                {item.avg_rating != null && item.review_count > 0
                  ? `${item.avg_rating.toFixed(1)} (${item.review_count})`
                  : t.discovery.newOnChair}
              </Text>
            </View>
          </View>

          {item.service_previews.length > 0 && (
            <Text style={styles.servicesSummary} numberOfLines={1}>
              {item.service_previews
                .slice(0, 3)
                .map((s) => (locale === "hi" ? s.display_name_hi : s.display_name_en))
                .join(" · ")}
            </Text>
          )}

          <View style={styles.cardFooterRow}>
            <View style={styles.rowGapSm}>
              <Clock
                size={14}
                color={
                  item.online_booking_paused
                    ? MOBILE_THEME.colors.danger
                    : MOBILE_THEME.colors.olivePrimary
                }
              />
              <Text
                style={[
                  styles.slotText,
                  item.online_booking_paused && styles.pausedSlotText,
                ]}
              >
                {item.online_booking_paused
                  ? t.discovery.pausedBadge
                  : item.next_available_slot_at
                    ? `${t.discovery.nextSlotPrefix}: ${formatIstTimeSlot(
                        item.next_available_slot_at,
                        locale
                      )}`
                    : t.discovery.noSlotsToday}
              </Text>
            </View>
            <Text style={styles.openStatusText}>
              {item.is_open_now ? t.discovery.openNow : t.discovery.closedNow}
            </Text>
          </View>
        </Pressable>
      );
    },
    [locale, router, t]
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      <FlashList
        data={items}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        estimatedItemSize={205}
        ListHeaderComponent={headerElement}
        ListFooterComponent={
          <VerifiedDisclaimerFooter
            disclaimerText={`${t.brand.verifiedBadge}: ${t.brand.verifiedDisclaimer}`}
          />
        }
        contentContainerStyle={styles.listContent}
        refreshing={branchesQuery.isRefetching}
        onRefresh={() => void branchesQuery.refetch()}
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
    paddingHorizontal: MOBILE_THEME.spacing.lg,
    paddingBottom: MOBILE_THEME.spacing.xl,
  },
  listHeader: {
    paddingTop: MOBILE_THEME.spacing.md,
    gap: MOBILE_THEME.spacing.md,
    paddingBottom: MOBILE_THEME.spacing.md,
  },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: MOBILE_THEME.spacing.md,
  },
  titleBlock: {
    flex: 1,
  },
  brandMark: {
    fontSize: 13,
    fontWeight: "700",
    color: MOBILE_THEME.colors.bronzeAccent,
    letterSpacing: 1,
  },
  headingText: {
    marginTop: 2,
    fontSize: 24,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  subtitleText: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 19,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  pillsRow: {
    gap: MOBILE_THEME.spacing.sm,
    paddingVertical: 2,
  },
  chipButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    borderRadius: MOBILE_THEME.radii.pill,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    ...Platform.select({
      web: { cursor: "pointer" as unknown as undefined },
    }),
  },
  chipButtonActive: {
    backgroundColor: MOBILE_THEME.colors.olivePrimary,
    borderColor: MOBILE_THEME.colors.olivePrimary,
  },
  chipText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  chipTextActive: {
    color: MOBILE_THEME.colors.white,
  },
  permissionBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.dangerSoft,
  },
  gpsErrorBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
    padding: MOBILE_THEME.spacing.md,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
  },
  permissionText: {
    flex: 1,
    fontSize: 12,
    color: MOBILE_THEME.colors.charcoalInk,
  },
  searchBar: {
    minHeight: TOUCH_TARGET_MIN_DP,
    flexDirection: "row",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
    paddingHorizontal: 14,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.white,
  },
  searchInput: {
    flex: 1,
    minHeight: TOUCH_TARGET_MIN_DP,
    fontSize: 15,
    color: MOBILE_THEME.colors.charcoalInk,
  },
  branchCard: {
    marginBottom: MOBILE_THEME.spacing.md,
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    gap: MOBILE_THEME.spacing.sm,
    ...Platform.select({
      web: { cursor: "pointer" as unknown as undefined },
    }),
  },
  cardHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: MOBILE_THEME.spacing.md,
  },
  cardTitle: {
    fontSize: 17,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  mutedText: {
    marginTop: 2,
    fontSize: 13,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  priceBadge: {
    alignItems: "flex-end",
  },
  priceCaption: {
    fontSize: 11,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  priceValue: {
    fontSize: 16,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  badgesRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: MOBILE_THEME.spacing.xs,
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
  verifiedBadgeText: {
    fontSize: 11,
    fontWeight: "700",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  featuredBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.bronzeSoft,
  },
  featuredBadgeText: {
    fontSize: 11,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
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
  neutralBadgeText: {
    fontSize: 11,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
  servicesSummary: {
    fontSize: 13,
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  cardFooterRow: {
    marginTop: 4,
    paddingTop: MOBILE_THEME.spacing.sm,
    borderTopWidth: 1,
    borderTopColor: MOBILE_THEME.colors.ivoryBorder,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: MOBILE_THEME.spacing.sm,
  },
  rowGapSm: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  slotText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.olivePrimary,
  },
  pausedSlotText: {
    color: MOBILE_THEME.colors.danger,
  },
  openStatusText: {
    fontSize: 12,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalMuted,
  },
  stateCard: {
    padding: MOBILE_THEME.spacing.lg,
    borderRadius: MOBILE_THEME.radii.md,
    borderWidth: 1,
    borderColor: MOBILE_THEME.colors.ivoryBorder,
    backgroundColor: MOBILE_THEME.colors.ivorySurface,
    alignItems: "center",
    gap: MOBILE_THEME.spacing.md,
  },
  stateText: {
    fontSize: 14,
    color: MOBILE_THEME.colors.charcoalMuted,
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
  retryButton: {
    minHeight: TOUCH_TARGET_MIN_DP,
    paddingHorizontal: 16,
    borderRadius: MOBILE_THEME.radii.sm,
    backgroundColor: MOBILE_THEME.colors.charcoalInk,
    alignSelf: "flex-start",
    alignItems: "center",
    justifyContent: "center",
  },
  retryText: {
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
  },
  secondaryButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: MOBILE_THEME.colors.charcoalInk,
  },
});
