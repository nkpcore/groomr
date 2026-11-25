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
