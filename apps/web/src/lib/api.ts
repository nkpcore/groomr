import type {
  AdminVerificationsResponseDto,
  ApiErrorEnvelope,
  AuditLogListResponseDto,
  AuthTokenResponse,
  BookingDetailDto,
  BookingListResponseDto,
  BranchAccessResponseDto,
  BranchResourceDto,
  BranchSetupStateDto,
  ConsentsResponseDto,
  DocumentReviewStatus,
  DocumentType,
  HealthResponse,
  OTPRequestPayload,
  OTPRequestResponse,
  OTPVerifyPayload,
  PartnerBranchServiceDto,
  PartnerContextResponseDto,
  PlatformMetaResponse,
  ResourceType,
  SalonDocumentDto,
  ScheduleBlockDto,
  ScheduleBlockType,
  SupportedLocale,
  UpdateConsentsRequestDto,
  UpdateProfileRequestDto,
  UserProfileDto,
  UserRole,
  WalkInItemDto,
  WalkInStatus,
} from "@chair/shared-types";

export interface ApiProbeResult {
  state: "ok" | "offline" | "error";
  health?: HealthResponse;
  meta?: PlatformMetaResponse;
  message?: string;
}

export interface StoredWebSession {
  accessToken: string;
  refreshToken: string;
  userId: string;
  roles: UserRole[];
  preferredLocale: SupportedLocale;
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

const SESSION_STORAGE_KEY = "chair.auth.session.v1";
let sessionGeneration = 0;

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

export function isBrowserOnline(): boolean {
  if (typeof navigator === "undefined" || typeof navigator.onLine !== "boolean") {
    return true;
  }
  return navigator.onLine;
}

export function loadWebSession(): StoredWebSession | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<StoredWebSession>;
    if (!parsed.accessToken || !parsed.refreshToken || !parsed.userId) {
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken,
      userId: parsed.userId,
      roles: Array.isArray(parsed.roles) ? parsed.roles : [],
      preferredLocale: parsed.preferredLocale === "hi" ? "hi" : "en",
    };
  } catch {
    return null;
  }
}

export function saveWebSession(session: StoredWebSession): void {
  sessionGeneration += 1;
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearWebSession(): void {
  sessionGeneration += 1;
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

export function sessionFromTokenResponse(res: AuthTokenResponse): StoredWebSession {
  return {
    accessToken: res.access_token,
    refreshToken: res.refresh_token,
    userId: res.user_id,
    roles: res.roles,
    preferredLocale: res.preferred_locale,
  };
}

export async function fetchFoundationProbe(
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl(),
  isOnline: boolean = isBrowserOnline()
): Promise<ApiProbeResult> {
  if (!isOnline) {
    return { state: "offline" };
  }

  try {
    const [healthRes, metaRes] = await Promise.all([
      fetchImpl(`${baseUrl}/health`, { cache: "no-store" }),
      fetchImpl(`${baseUrl}/meta`, { cache: "no-store" }),
    ]);

    if (!healthRes.ok || !metaRes.ok) {
      return {
        state: "error",
        message: `HTTP ${healthRes.status}/${metaRes.status}`,
      };
    }

    const [health, meta] = await Promise.all([
      healthRes.json() as Promise<HealthResponse>,
      metaRes.json() as Promise<PlatformMetaResponse>,
    ]);

    return { state: "ok", health, meta };
  } catch (err) {
    return {
      state: "error",
      message: err instanceof Error ? err.message : "Network error",
    };
  }
}

async function parseErrorResponse(res: Response): Promise<ApiClientError> {
  try {
    const body = (await res.json()) as Partial<ApiErrorEnvelope>;
    if (body.error?.code && body.error?.message) {
      return new ApiClientError(res.status, body.error.code, body.error.message);
    }
  } catch {
    // Ignore JSON parse fallback
  }
  return new ApiClientError(res.status, `HTTP_${res.status}`, `HTTP ${res.status}`);
}

async function rawJsonRequest<T>(
  path: string,
  init: RequestInit = {},
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl()
): Promise<T> {
  if (!isBrowserOnline()) {
    throw new ApiClientError(0, "OFFLINE", "You appear to be offline.");
  }

  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetchImpl(`${baseUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiClientError(
      0,
      "NETWORK_ERROR",
      err instanceof Error ? err.message : "Network error"
    );
  }

  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return (await res.json()) as T;
}

let activeRefreshPromise: Promise<StoredWebSession | null> | null = null;

async function rotateStoredSession(
  current: StoredWebSession,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl()
): Promise<StoredWebSession | null> {
  if (!activeRefreshPromise) {
    const startGeneration = sessionGeneration;
    activeRefreshPromise = (async () => {
      try {
        const latestStored = loadWebSession();
        if (latestStored && latestStored.refreshToken !== current.refreshToken) {
          return latestStored;
        }
        const refreshed = await rawJsonRequest<AuthTokenResponse>(
          "/auth/refresh",
          {
            method: "POST",
            body: JSON.stringify({ refresh_token: current.refreshToken }),
          },
          fetchImpl,
          baseUrl
        );
        if (sessionGeneration !== startGeneration) {
          return null;
        }
        const nextSession = sessionFromTokenResponse(refreshed);
        saveWebSession(nextSession);
        return nextSession;
      } catch (err) {
        if (
          sessionGeneration === startGeneration &&
          err instanceof ApiClientError &&
          (err.status === 401 || err.status === 403)
        ) {
          clearWebSession();
        }
        return null;
      } finally {
        activeRefreshPromise = null;
      }
    })();
  }
  return activeRefreshPromise;
}

export async function authorizedRequest<T>(
  path: string,
  session: StoredWebSession,
  init: RequestInit = {},
  onSessionUpdate?: (next: StoredWebSession | null) => void,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl()
): Promise<T> {
  const executeWithToken = (token: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return rawJsonRequest<T>(path, { ...init, headers }, fetchImpl, baseUrl);
  };

  try {
    return await executeWithToken(session.accessToken);
  } catch (err) {
    if (err instanceof ApiClientError && err.status === 401) {
      const nextSession = await rotateStoredSession(session, fetchImpl, baseUrl);
      if (nextSession) {
        onSessionUpdate?.(nextSession);
        return executeWithToken(nextSession.accessToken);
      }
      onSessionUpdate?.(null);
    }
    throw err;
  }
}

export function requestOtp(
  payload: OTPRequestPayload,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl()
): Promise<OTPRequestResponse> {
  return rawJsonRequest<OTPRequestResponse>(
    "/auth/otp/request",
    { method: "POST", body: JSON.stringify(payload) },
    fetchImpl,
    baseUrl
  );
}

export function verifyOtp(
  payload: OTPVerifyPayload,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl()
): Promise<AuthTokenResponse> {
  return rawJsonRequest<AuthTokenResponse>(
    "/auth/otp/verify",
    { method: "POST", body: JSON.stringify(payload) },
    fetchImpl,
    baseUrl
  );
}

export async function logoutSession(
  session: StoredWebSession,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getApiBaseUrl()
): Promise<void> {
  clearWebSession();
  try {
    await rawJsonRequest<{ status: string }>(
      "/auth/logout",
      {
        method: "POST",
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      },
      fetchImpl,
      baseUrl
    );
  } catch {
    // Local session is already invalidated even if offline or expired.
  }
}

export function fetchMyProfile(
  session: StoredWebSession,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<UserProfileDto> {
  return authorizedRequest<UserProfileDto>("/users/me", session, {}, onSessionUpdate);
}

export function updateMyProfile(
  session: StoredWebSession,
  payload: UpdateProfileRequestDto,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<UserProfileDto> {
  return authorizedRequest<UserProfileDto>(
    "/users/me",
    session,
    { method: "PATCH", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function fetchMyConsents(
  session: StoredWebSession,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<ConsentsResponseDto> {
  return authorizedRequest<ConsentsResponseDto>("/users/me/consents", session, {}, onSessionUpdate);
}

export function updateMyConsents(
  session: StoredWebSession,
  payload: UpdateConsentsRequestDto,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<ConsentsResponseDto> {
  return authorizedRequest<ConsentsResponseDto>(
    "/users/me/consents",
    session,
    { method: "PUT", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function fetchPartnerContext(
  session: StoredWebSession,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<PartnerContextResponseDto> {
  return authorizedRequest<PartnerContextResponseDto>("/partner/context", session, {}, onSessionUpdate);
}

export function fetchPartnerBranchAccess(
  session: StoredWebSession,
  branchId: string,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<BranchAccessResponseDto> {
  return authorizedRequest<BranchAccessResponseDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/access`,
    session,
    {},
    onSessionUpdate
  );
}

export function fetchAdminAuditLogs(
  session: StoredWebSession,
  limit: number = 25,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<AuditLogListResponseDto> {
  return authorizedRequest<AuditLogListResponseDto>(
    `/admin/audit-logs?limit=${limit}`,
    session,
    {},
    onSessionUpdate
  );
}

export function createPartnerSalon(
  session: StoredWebSession,
  payload: {
    legal_name: string;
    brand_name: string;
    gstin?: string | null;
    pan_masked?: string | null;
    branch_name: string;
    address_line1: string;
    city: string;
    state: string;
    pincode: string;
    lat: number;
    lng: number;
    initial_chair_count?: number;
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ salon: { id: string }; branch: { id: string; slug: string } }> {
  return authorizedRequest(
    "/partner/salons",
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function fetchPartnerBranchSetup(
  session: StoredWebSession,
  branchId: string,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<BranchSetupStateDto> {
  return authorizedRequest<BranchSetupStateDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/setup`,
    session,
    {},
    onSessionUpdate
  );
}

export function togglePartnerBranchPause(
  session: StoredWebSession,
  branchId: string,
  paused: boolean,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ branch_id: string; online_booking_paused: boolean }> {
  return authorizedRequest(
    `/partner/branches/${encodeURIComponent(branchId)}/pause`,
    session,
    { method: "PATCH", body: JSON.stringify({ paused }) },
    onSessionUpdate
  );
}

export function fetchPartnerBranchBookings(
  session: StoredWebSession,
  branchId: string,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<BookingListResponseDto> {
  return authorizedRequest<BookingListResponseDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/bookings`,
    session,
    {},
    onSessionUpdate
  );
}

export function partnerTransitionBooking(
  session: StoredWebSession,
  branchId: string,
  bookingId: string,
  action: "check-in" | "start" | "complete" | "no-show" | "cancel",
  body: Record<string, unknown>,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<BookingDetailDto> {
  const headers: Record<string, string> = {};
  if (action === "cancel") {
    headers["Idempotency-Key"] =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `cancel-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
  return authorizedRequest<BookingDetailDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/bookings/${encodeURIComponent(bookingId)}/${action}`,
    session,
    { method: "POST", headers, body: JSON.stringify(body) },
    onSessionUpdate
  );
}

export function fetchPartnerWalkIns(
  session: StoredWebSession,
  branchId: string,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ items: WalkInItemDto[] }> {
  return authorizedRequest<{ items: WalkInItemDto[] }>(
    `/partner/branches/${encodeURIComponent(branchId)}/walk-ins`,
    session,
    {},
    onSessionUpdate
  );
}

export function createPartnerWalkIn(
  session: StoredWebSession,
  branchId: string,
  payload: {
    customer_name: string;
    customer_phone_e164?: string | null;
    service_summary: string;
    quoted_price_paise: number;
    estimated_duration_minutes: number;
    staff_id?: string | null;
    resource_id?: string | null;
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<WalkInItemDto> {
  return authorizedRequest<WalkInItemDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/walk-ins`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function updatePartnerWalkIn(
  session: StoredWebSession,
  branchId: string,
  walkInId: string,
  payload: { status: WalkInStatus; staff_id?: string | null; resource_id?: string | null },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<WalkInItemDto> {
  return authorizedRequest<WalkInItemDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/walk-ins/${encodeURIComponent(walkInId)}`,
    session,
    { method: "PATCH", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function updatePartnerBranchHours(
  session: StoredWebSession,
  branchId: string,
  operating_hours: Record<string, { open: string; close: string } | null>,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ branch_id: string }> {
  return authorizedRequest(
    `/partner/branches/${encodeURIComponent(branchId)}/hours`,
    session,
    { method: "PATCH", body: JSON.stringify({ operating_hours }) },
    onSessionUpdate
  );
}

export function createPartnerBranchService(
  session: StoredWebSession,
  branchId: string,
  payload: {
    service_id: string;
    display_name_en: string;
    display_name_hi: string;
    price_paise: number;
    duration_minutes: number;
    buffer_before_minutes?: number;
    buffer_after_minutes?: number;
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<PartnerBranchServiceDto> {
  return authorizedRequest<PartnerBranchServiceDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/services`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function updatePartnerBranchService(
  session: StoredWebSession,
  branchId: string,
  branchServiceId: string,
  payload: { is_active?: boolean; price_paise?: number; duration_minutes?: number },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<PartnerBranchServiceDto> {
  return authorizedRequest<PartnerBranchServiceDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/services/${encodeURIComponent(branchServiceId)}`,
    session,
    { method: "PATCH", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function createPartnerStaff(
  session: StoredWebSession,
  branchId: string,
  payload: {
    display_name: string;
    bio?: string | null;
    specializations?: string[];
    qualified_branch_service_ids: string[];
    shifts: { weekday: number; start_time: string; end_time: string; timezone?: string }[];
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ id: string }> {
  return authorizedRequest(
    `/partner/branches/${encodeURIComponent(branchId)}/staff`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function createPartnerScheduleBlock(
  session: StoredWebSession,
  branchId: string,
  payload: {
    staff_id?: string | null;
    block_type: ScheduleBlockType;
    start_at: string;
    end_at: string;
    reason?: string | null;
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<ScheduleBlockDto> {
  return authorizedRequest<ScheduleBlockDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/blocks`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function deletePartnerScheduleBlock(
  session: StoredWebSession,
  branchId: string,
  blockId: string,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ deleted: boolean }> {
  return authorizedRequest(
    `/partner/branches/${encodeURIComponent(branchId)}/blocks/${encodeURIComponent(blockId)}`,
    session,
    { method: "DELETE" },
    onSessionUpdate
  );
}

export function createPartnerResource(
  session: StoredWebSession,
  branchId: string,
  payload: { name: string; resource_type: ResourceType; is_active?: boolean },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<BranchResourceDto> {
  return authorizedRequest<BranchResourceDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/resources`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function uploadPartnerDocument(
  session: StoredWebSession,
  branchId: string,
  payload: { document_type: DocumentType; mime_type: string; content_base64: string },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<SalonDocumentDto> {
  return authorizedRequest<SalonDocumentDto>(
    `/partner/branches/${encodeURIComponent(branchId)}/documents`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function fetchAdminVerifications(
  session: StoredWebSession,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<AdminVerificationsResponseDto> {
  return authorizedRequest<AdminVerificationsResponseDto>(
    "/admin/verifications",
    session,
    {},
    onSessionUpdate
  );
}

export function reviewAdminDocument(
  session: StoredWebSession,
  documentId: string,
  payload: { review_status: Exclude<DocumentReviewStatus, "PENDING">; rejection_reason?: string | null },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<SalonDocumentDto> {
  return authorizedRequest<SalonDocumentDto>(
    `/admin/documents/${encodeURIComponent(documentId)}`,
    session,
    { method: "PATCH", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function recordAdminInspection(
  session: StoredWebSession,
  branchId: string,
  payload: {
    numerical_score: number;
    single_use_blades_ok: boolean;
    sharps_disposal_ok: boolean;
    instrument_disinfection_ok: boolean;
    fresh_towels_ok: boolean;
    corrective_action_notes?: string | null;
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ branch_status: string; verification_status: string }> {
  return authorizedRequest(
    `/admin/branches/${encodeURIComponent(branchId)}/inspections`,
    session,
    { method: "POST", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function updateAdminBranchGovernance(
  session: StoredWebSession,
  branchId: string,
  payload: {
    status?: string | null;
    verification_status?: string | null;
    is_featured?: boolean | null;
    featured_disclosure_label?: string | null;
    notes?: string | null;
  },
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{
  branch_id: string;
  status: string;
  verification_status: string;
  is_featured: boolean;
  featured_disclosure_label: string | null;
}> {
  return authorizedRequest(
    `/admin/branches/${encodeURIComponent(branchId)}/governance`,
    session,
    { method: "PATCH", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export async function fetchSignedPrivateAsset(
  session: StoredWebSession,
  signedPath: string,
  onSessionUpdate?: (next: StoredWebSession | null) => void
): Promise<{ blobUrl: string; mimeType: string }> {
  if (!isBrowserOnline()) {
    throw new ApiClientError(0, "OFFLINE", "Browser appears offline.");
  }
  const origin = getApiBaseUrl().replace(/\/api\/v1\/?$/, "");
  const fullUrl = signedPath.startsWith("http") ? signedPath : `${origin}${signedPath}`;

  const tryFetch = (token: string) =>
    fetch(fullUrl, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });

  let res = await tryFetch(session.accessToken);
  if (res.status === 401) {
    const next = await rotateStoredSession(session);
    if (next) {
      onSessionUpdate?.(next);
      res = await tryFetch(next.accessToken);
    } else {
      onSessionUpdate?.(null);
    }
  }
  if (!res.ok) {
    throw new ApiClientError(res.status, "SIGNED_ASSET_FETCH_FAILED", `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  return {
    blobUrl: URL.createObjectURL(blob),
    mimeType: res.headers.get("content-type") || blob.type || "application/octet-stream",
  };
}
