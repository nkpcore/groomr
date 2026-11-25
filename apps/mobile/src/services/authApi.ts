import type {
  ApiErrorEnvelope,
  AuthTokenResponse,
  ConsentsResponseDto,
  OTPRequestPayload,
  OTPRequestResponse,
  OTPVerifyPayload,
  UpdateConsentsRequestDto,
  UpdateProfileRequestDto,
  UserProfileDto,
} from "@chair/shared-types";
import { getMobileApiBaseUrl } from "./health";
import {
  clearMobileSession,
  getMobileSessionEpoch,
  loadMobileSession,
  mobileSessionFromTokens,
  saveMobileSession,
  type StoredMobileSession,
} from "./tokenStorage";

export class MobileApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "MobileApiError";
    this.status = status;
    this.code = code;
  }
}

async function parseMobileError(res: Response): Promise<MobileApiError> {
  try {
    const body = (await res.json()) as Partial<ApiErrorEnvelope>;
    if (body.error?.code && body.error?.message) {
      return new MobileApiError(res.status, body.error.code, body.error.message);
    }
  } catch {
    // Fallback to HTTP status
  }
  return new MobileApiError(res.status, `HTTP_${res.status}`, `HTTP ${res.status}`);
}

async function rawMobileJson<T>(
  path: string,
  init: RequestInit = {},
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    throw new MobileApiError(0, "OFFLINE", "You appear to be offline.");
  }

  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetchImpl(`${baseUrl}${path}`, { ...init, headers });
  } catch (err) {
    throw new MobileApiError(
      0,
      "NETWORK_ERROR",
      err instanceof Error ? err.message : "Network unavailable"
    );
  }

  if (!res.ok) {
    throw await parseMobileError(res);
  }
  return (await res.json()) as T;
}

let mobileRefreshPromise: Promise<StoredMobileSession | null> | null = null;

async function rotateMobileSession(
  session: StoredMobileSession,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<StoredMobileSession | null> {
  if (!mobileRefreshPromise) {
    const startEpoch = getMobileSessionEpoch();
    mobileRefreshPromise = (async () => {
      try {
        const latestStored = await loadMobileSession();
        if (latestStored && latestStored.refreshToken !== session.refreshToken) {
          return latestStored;
        }
        const refreshed = await rawMobileJson<AuthTokenResponse>(
          "/auth/refresh",
          {
            method: "POST",
            body: JSON.stringify({ refresh_token: session.refreshToken }),
          },
          fetchImpl,
          baseUrl
        );
        if (getMobileSessionEpoch() !== startEpoch) {
          return null;
        }
        const next = mobileSessionFromTokens(refreshed);
        await saveMobileSession(next);
        return next;
      } catch (err) {
        if (
          getMobileSessionEpoch() === startEpoch &&
          err instanceof MobileApiError &&
          (err.status === 401 || err.status === 403)
        ) {
          await clearMobileSession();
        }
        return null;
      } finally {
        mobileRefreshPromise = null;
      }
    })();
  }
  return mobileRefreshPromise;
}

export async function authorizedMobileRequest<T>(
  path: string,
  session: StoredMobileSession,
  init: RequestInit = {},
  onSessionUpdate?: (next: StoredMobileSession | null) => void,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<T> {
  const exec = (token: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return rawMobileJson<T>(path, { ...init, headers }, fetchImpl, baseUrl);
  };

  try {
    return await exec(session.accessToken);
  } catch (err) {
    if (err instanceof MobileApiError && err.status === 401) {
      const next = await rotateMobileSession(session, fetchImpl, baseUrl);
      if (next) {
        onSessionUpdate?.(next);
        return exec(next.accessToken);
      }
      onSessionUpdate?.(null);
    }
    throw err;
  }
}

export function requestMobileOtp(payload: OTPRequestPayload): Promise<OTPRequestResponse> {
  return rawMobileJson<OTPRequestResponse>("/auth/otp/request", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function verifyMobileOtp(payload: OTPVerifyPayload): Promise<AuthTokenResponse> {
  return rawMobileJson<AuthTokenResponse>("/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function logoutMobileSession(session: StoredMobileSession): Promise<void> {
  await clearMobileSession();
  try {
    await rawMobileJson<{ status: string }>("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: session.refreshToken }),
    });
  } catch {
    // Local session is cleared even if offline or expired.
  }
}

export function fetchMobileProfile(
  session: StoredMobileSession,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<UserProfileDto> {
  return authorizedMobileRequest<UserProfileDto>("/users/me", session, {}, onSessionUpdate);
}

export function updateMobileProfile(
  session: StoredMobileSession,
  payload: UpdateProfileRequestDto,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<UserProfileDto> {
  return authorizedMobileRequest<UserProfileDto>(
    "/users/me",
    session,
    { method: "PATCH", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}

export function updateMobileConsents(
  session: StoredMobileSession,
  payload: UpdateConsentsRequestDto,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<ConsentsResponseDto> {
  return authorizedMobileRequest<ConsentsResponseDto>(
    "/users/me/consents",
    session,
    { method: "PUT", body: JSON.stringify(payload) },
    onSessionUpdate
  );
}
