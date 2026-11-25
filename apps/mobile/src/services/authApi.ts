import type {
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
import { MobileApiError, rawMobileJson } from "./http";
import {
  clearMobileSession,
  getMobileSessionEpoch,
  loadMobileSession,
  mobileSessionFromTokens,
  saveMobileSession,
  type StoredMobileSession,
} from "./tokenStorage";

export { MobileApiError };

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
