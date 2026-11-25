import enMessages from "./i18n/en.json" with { type: "json" };
import hiMessages from "./i18n/hi.json" with { type: "json" };

export type SupportedLocale = "en" | "hi";

export type UserRole = "CUSTOMER" | "PARTNER_OWNER" | "PARTNER_STAFF" | "ADMIN";

export type ConsentType =
  | "TERMS"
  | "PRIVACY_DPDP"
  | "MARKETING"
  | "LOCATION"
  | "STYLE_PASSPORT_PHOTOS";

export const ALL_CONSENT_TYPES: readonly ConsentType[] = [
  "TERMS",
  "PRIVACY_DPDP",
  "LOCATION",
  "STYLE_PASSPORT_PHOTOS",
  "MARKETING",
] as const;

export type BookingStatus =
  | "HELD"
  | "REQUESTED"
  | "CONFIRMED"
  | "CHECKED_IN"
  | "IN_SERVICE"
  | "COMPLETED"
  | "CANCELLED"
  | "EXPIRED"
  | "NO_SHOW";

export type ServiceCategory =
  | "HAIRCUT"
  | "BEARD"
  | "SHAVE"
  | "FACIAL"
  | "PACKAGE"
  | "COLOR";

export type BranchVerificationStatus =
  | "UNVERIFIED"
  | "PENDING"
  | "CHAIR_VERIFIED"
  | "ACTION_REQUIRED"
  | "SUSPENDED";

export interface DependencyCheck {
  status: "ok" | "unavailable";
  detail?: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  service: string;
  version: string;
  environment: string;
  timestamp_utc: string;
  booking_hold_ttl_seconds: number;
  adapters: {
    auth_otp: string;
    payments: string;
    storage: string;
    maps: string;
    notifications: string;
  };
  checks: {
    database: DependencyCheck;
    postgis: DependencyCheck;
    redis: DependencyCheck;
  };
}

export interface PlatformMetaResponse {
  brand: string;
  currency: "INR";
  supported_locales: SupportedLocale[];
  booking_hold_ttl_seconds: number;
  verification_badge_disclaimer: string;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string | null;
  };
}

export interface OTPRequestPayload {
  phone_e164: string;
}

export interface OTPRequestResponse {
  challenge_id: string;
  masked_phone: string;
  expires_in_seconds: number;
  delivery_mode: string;
}

export interface OTPVerifyPayload {
  challenge_id: string;
  phone_e164: string;
  otp_code: string;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  refresh_expires_in_seconds: number;
  user_id: string;
  roles: UserRole[];
  preferred_locale: SupportedLocale;
}

export interface RoleScopeDto {
  id: string;
  role: UserRole;
  salon_id: string | null;
  branch_id: string | null;
}

export interface CurrentConsentStateDto {
  consent_type: ConsentType;
  granted: boolean;
  version: string;
  granted_at: string | null;
  revoked_at: string | null;
}

export interface ConsentHistoryItemDto {
  id: string;
  consent_type: ConsentType;
  version: string;
  granted: boolean;
  granted_at: string;
  revoked_at: string | null;
  created_at: string;
}

export interface ConsentsResponseDto {
  consents: CurrentConsentStateDto[];
  history: ConsentHistoryItemDto[];
}

export interface UserProfileDto {
  id: string;
  phone_e164: string;
  email: string | null;
  full_name: string | null;
  preferred_locale: SupportedLocale;
  is_active: boolean;
  last_login_at: string | null;
  roles: RoleScopeDto[];
  consents: CurrentConsentStateDto[];
}

export interface UpdateProfileRequestDto {
  full_name?: string | null;
  email?: string | null;
  preferred_locale?: SupportedLocale;
}

export interface ConsentDecisionInputDto {
  consent_type: ConsentType;
  granted: boolean;
  version: string;
}

export interface UpdateConsentsRequestDto {
  decisions: ConsentDecisionInputDto[];
}

export interface PartnerSalonSummaryDto {
  id: string;
  brand_name: string;
  legal_name: string;
  status: string;
  verification_badge_status: string;
}

export interface PartnerBranchSummaryDto {
  id: string;
  salon_id: string;
  name: string;
  city: string;
  state: string;
  status: string;
  verification_status: string;
  online_booking_paused: boolean;
}

export interface PartnerContextResponseDto {
  salons: PartnerSalonSummaryDto[];
  branches: PartnerBranchSummaryDto[];
}

export interface BranchAccessResponseDto {
  branch_id: string;
  salon_id: string;
  name: string;
  city: string;
  status: string;
  verification_status: string;
}

export interface AuditLogItemDto {
  id: string;
  actor_user_id: string | null;
  actor_role: string;
  action: string;
  resource_type: string;
  resource_id: string;
  branch_id: string | null;
  request_id: string | null;
  after_state_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListResponseDto {
  items: AuditLogItemDto[];
}

export interface BranchServicePreviewDto {
  id: string;
  code: string;
  category: ServiceCategory;
  display_name_en: string;
  display_name_hi: string;
  description: string | null;
  price_paise: number;
  duration_minutes: number;
  buffer_before_minutes: number;
  buffer_after_minutes: number;
}

export interface BranchDiscoveryItemDto {
  id: string;
  salon_id: string;
  brand_name: string;
  name: string;
  slug: string;
  address_line1: string;
  city: string;
  state: string;
  pincode: string;
  lat: number;
  lng: number;
  distance_meters: number | null;
  verification_status: BranchVerificationStatus;
  is_featured: boolean;
  featured_disclosure_label: string | null;
  online_booking_paused: boolean;
  is_open_now: boolean;
  starting_price_paise: number | null;
  avg_rating: number | null;
  review_count: number;
  categories: ServiceCategory[];
  service_previews: BranchServicePreviewDto[];
  next_available_slot_at: string | null;
}

export interface BranchListResponseDto {
  items: BranchDiscoveryItemDto[];
  total_count: number;
  verification_badge_disclaimer: string;
}

export interface PublicStaffItemDto {
  id: string;
  display_name: string;
  bio: string | null;
  specializations: string[];
  is_verified_staff: boolean;
  is_accepting_bookings: boolean;
  qualified_branch_service_ids: string[];
}

export interface PublicReviewItemDto {
  id: string;
  rating: number;
  hygiene_rating: number;
  comment: string | null;
  created_at: string;
}

export interface RatingSummaryDto {
  avg_rating: number | null;
  avg_hygiene_rating: number | null;
  review_count: number;
  recent_reviews: PublicReviewItemDto[];
}

export interface InspectionSummaryDto {
  overall_outcome: string;
  completed_at: string | null;
  numerical_score: number | null;
}

export interface BranchDetailResponseDto {
  id: string;
  salon_id: string;
  brand_name: string;
  name: string;
  slug: string;
  address_line1: string;
  address_line2: string | null;
  city: string;
  state: string;
  pincode: string;
  lat: number;
  lng: number;
  operating_hours_json: Record<string, { open?: string; close?: string; closed?: boolean }>;
  verification_status: BranchVerificationStatus;
  verification_badge_disclaimer: string;
  is_featured: boolean;
  featured_disclosure_label: string | null;
  online_booking_paused: boolean;
  is_open_now: boolean;
  chair_count: number;
  services: BranchServicePreviewDto[];
  staff: PublicStaffItemDto[];
  rating_summary: RatingSummaryDto;
  latest_inspection: InspectionSummaryDto | null;
}

export interface SlotStaffOptionDto {
  staff_id: string;
  display_name: string;
  is_verified_staff: boolean;
  duration_minutes: number;
  end_at: string;
}

export interface AvailableSlotDto {
  start_at: string;
  end_at: string;
  duration_minutes: number;
  available_staff: SlotStaffOptionDto[];
  available_chair_count: number;
}

export interface AvailabilityResponseDto {
  branch_id: string;
  date: string;
  timezone: string;
  online_booking_paused: boolean;
  is_branch_closed: boolean;
  slots: AvailableSlotDto[];
}

export const CHAIR_PALETTE = {
  ivoryCanvas: "#FAF7F2",
  ivorySurface: "#F4EFE6",
  ivoryBorder: "#E2DACD",
  charcoalInk: "#1C1B19",
  charcoalMuted: "#524E48",
  olivePrimary: "#4A5D4E",
  oliveSoft: "#E7ECE8",
  bronzeAccent: "#9C744F",
  bronzeSoft: "#F3EAE1",
  danger: "#9E3B33",
  dangerSoft: "#F9ECEA",
  white: "#FFFFFF",
} as const;

export const I18N_DICTIONARIES = {
  en: enMessages,
  hi: hiMessages,
} as const;

export type TranslationCatalog = typeof enMessages;

export function getTranslations(locale: SupportedLocale): TranslationCatalog {
  return I18N_DICTIONARIES[locale] ?? enMessages;
}

/**
 * Normalize Indian 10-digit mobile numbers or international E.164 phone strings.
 * Returns null if the phone cannot form a valid E.164 number.
 */
export function normalizePhoneE164(raw: string): string | null {
  const trimmed = raw.trim().replace(/[\s()-]/g, "");
  if (/^\+[1-9]\d{7,14}$/.test(trimmed)) {
    return trimmed;
  }
  if (/^[6-9]\d{9}$/.test(trimmed)) {
    return `+91${trimmed}`;
  }
  if (/^91[6-9]\d{9}$/.test(trimmed)) {
    return `+${trimmed}`;
  }
  return null;
}

export function isValidOtpCode(raw: string): boolean {
  return /^\d{6}$/.test(raw.trim());
}

/**
 * Format integer paise (INR) for display without floating-point money math.
 * Example: 49900 -> "₹499", 49950 -> "₹499.50"
 */
export function formatINRFromPaise(paise: number): string {
  if (!Number.isInteger(paise)) {
    throw new RangeError("Monetary amount must be an integer number of paise.");
  }
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const wholeRupees = Math.floor(abs / 100);
  const remPaise = abs % 100;
  const formattedRupees = wholeRupees.toLocaleString("en-IN");
  if (remPaise === 0) {
    return `${sign}₹${formattedRupees}`;
  }
  return `${sign}₹${formattedRupees}.${String(remPaise).padStart(2, "0")}`;
}

export function formatDistanceMeters(
  meters: number | null | undefined,
  locale: SupportedLocale = "en"
): string | null {
  if (meters === null || meters === undefined || Number.isNaN(meters)) {
    return null;
  }
  if (meters < 1000) {
    return locale === "hi" ? `${Math.round(meters)} मी` : `${Math.round(meters)} m`;
  }
  const km = (Math.round((meters / 1000) * 10) / 10).toFixed(1);
  return locale === "hi" ? `${km} किमी` : `${km} km`;
}

export function formatDurationMinutes(
  minutes: number,
  locale: SupportedLocale = "en"
): string {
  return locale === "hi" ? `${minutes} मिनट` : `${minutes} min`;
}

export function formatIstTimeSlot(isoUtc: string, locale: SupportedLocale = "en"): string {
  const dt = new Date(isoUtc);
  if (Number.isNaN(dt.getTime())) {
    return isoUtc;
  }
  return new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(dt);
}

export function formatIstDateTime(isoUtc: string, locale: SupportedLocale = "en"): string {
  const dt = new Date(isoUtc);
  if (Number.isNaN(dt.getTime())) {
    return isoUtc;
  }
  return new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(dt);
}

export type WalkInStatus =
  | "WAITING"
  | "SEATED"
  | "IN_SERVICE"
  | "COMPLETED"
  | "CANCELLED"
  | "NO_SHOW";

export interface CreateHoldRequestDto {
  branch_id: string;
  branch_service_ids: string[];
  start_at: string;
  staff_id?: string | null;
  notes?: string | null;
}

export interface HoldItemPreviewDto {
  branch_service_id: string;
  service_name_en: string;
  service_name_hi: string;
  category: ServiceCategory;
  unit_price_paise: number;
  duration_minutes: number;
}

export interface HoldCreationResponseDto {
  hold_id: string;
  booking_id: string;
  booking_code: string;
  status: BookingStatus;
  hold_status: "ACTIVE" | "CONVERTED" | "RELEASED" | "EXPIRED";
  expires_at: string;
  hold_ttl_seconds: number;
  branch_id: string;
  branch_name: string;
  staff_id: string;
  staff_name: string;
  resource_id: string | null;
  resource_name: string | null;
  scheduled_start_at: string;
  scheduled_end_at: string;
  total_price_paise: number;
  discount_paise: number;
  net_payable_paise: number;
  items: HoldItemPreviewDto[];
}

export interface BookingItemSnapshotDto {
  id: string;
  branch_service_id: string | null;
  service_name_snapshot: string;
  category_snapshot: ServiceCategory;
  unit_price_paise_snapshot: number;
  duration_minutes_snapshot: number;
}

export interface PaymentSummaryDto {
  id: string;
  provider: "PAY_AT_SALON" | "TEST_MODE" | "RAZORPAY";
  provider_order_id: string | null;
  provider_payment_id: string | null;
  amount_paise: number;
  currency: string;
  status: string;
  paid_at: string | null;
}

export interface RefundSummaryDto {
  id: string;
  amount_paise: number;
  reason: string;
  status: string;
  provider_refund_id: string | null;
}

export interface BookingDetailDto {
  id: string;
  booking_code: string;
  status: BookingStatus;
  source: "PLATFORM" | "WALK_IN";
  booking_mode: "INSTANT" | "REQUEST";
  branch_id: string;
  branch_name: string;
  branch_city: string;
  slot_hold_id: string | null;
  hold_expires_at: string | null;
  hold_status: string | null;
  staff_id: string | null;
  staff_name: string | null;
  resource_id: string | null;
  resource_name: string | null;
  scheduled_start_at: string;
  scheduled_end_at: string;
  total_price_paise: number;
  discount_paise: number;
  net_payable_paise: number;
  notes: string | null;
  check_in_otp: string | null;
  completion_otp: string | null;
  checked_in_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  items: BookingItemSnapshotDto[];
  payment: PaymentSummaryDto | null;
  refund: RefundSummaryDto | null;
  has_review: boolean;
}

export interface HoldDetailResponseDto {
  hold_id: string;
  hold_status: "ACTIVE" | "CONVERTED" | "RELEASED" | "EXPIRED";
  expires_at: string;
  hold_ttl_seconds: number;
  booking: BookingDetailDto;
}

export interface BookingListResponseDto {
  items: BookingDetailDto[];
}

export interface PaymentOrderResponseDto {
  payment_id: string;
  booking_id: string;
  provider: "TEST_MODE" | "RAZORPAY";
  provider_order_id: string;
  amount_paise: number;
  currency: string;
  status: string;
}

export interface CreateReviewRequestDto {
  rating: number;
  hygiene_rating: number;
  comment?: string | null;
}

export interface WalkInItemDto {
  id: string;
  branch_id: string;
  staff_id: string | null;
  resource_id: string | null;
  customer_name: string;
  customer_phone_e164: string | null;
  service_summary: string;
  quoted_price_paise: number;
  estimated_duration_minutes: number;
  queue_position: number;
  status: WalkInStatus;
  checked_in_at: string;
  completed_at: string | null;
}
