import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import type { AuthTokenResponse, SupportedLocale, UserRole } from "@chair/shared-types";

export interface StoredMobileSession {
  accessToken: string;
  refreshToken: string;
  userId: string;
  roles: UserRole[];
  preferredLocale: SupportedLocale;
}

const MOBILE_SESSION_KEY = "chair.mobile.auth.session.v1";
let memoryFallback: string | null = null;
let mobileSessionEpoch = 0;

export function getMobileSessionEpoch(): number {
  return mobileSessionEpoch;
}

export function mobileSessionFromTokens(res: AuthTokenResponse): StoredMobileSession {
  return {
    accessToken: res.access_token,
    refreshToken: res.refresh_token,
    userId: res.user_id,
    roles: res.roles,
    preferredLocale: res.preferred_locale,
  };
}

export async function saveMobileSession(session: StoredMobileSession): Promise<void> {
  mobileSessionEpoch += 1;
  const serialized = JSON.stringify(session);
  memoryFallback = serialized;

  if (Platform.OS === "web") {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(MOBILE_SESSION_KEY, serialized);
    }
    return;
  }

  await SecureStore.setItemAsync(MOBILE_SESSION_KEY, serialized);
}

export async function loadMobileSession(): Promise<StoredMobileSession | null> {
  let raw: string | null = memoryFallback;

  if (Platform.OS === "web") {
    if (typeof window !== "undefined") {
      raw = window.localStorage.getItem(MOBILE_SESSION_KEY);
    }
  } else {
    raw = await SecureStore.getItemAsync(MOBILE_SESSION_KEY);
  }

  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredMobileSession>;
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

export async function clearMobileSession(): Promise<void> {
  mobileSessionEpoch += 1;
  memoryFallback = null;
  if (Platform.OS === "web") {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(MOBILE_SESSION_KEY);
    }
    return;
  }

  await SecureStore.deleteItemAsync(MOBILE_SESSION_KEY);
}
