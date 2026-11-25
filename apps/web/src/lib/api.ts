import type {
  ApiErrorEnvelope,
  AuditLogListResponseDto,
  AuthTokenResponse,
  BranchAccessResponseDto,
  ConsentsResponseDto,
  HealthResponse,
  OTPRequestPayload,
  OTPRequestResponse,
  OTPVerifyPayload,
  PartnerContextResponseDto,
  PlatformMetaResponse,
  SupportedLocale,
  UpdateConsentsRequestDto,
  UpdateProfileRequestDto,
  UserProfileDto,
  UserRole,
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
