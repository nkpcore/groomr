import type { HealthResponse } from "@chair/shared-types";

export type MobileHealthProbe =
  | { state: "ok"; data: HealthResponse }
  | { state: "error"; message: string };

export function getMobileApiBaseUrl(): string {
  return process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

export async function fetchMobileHealth(
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<MobileHealthProbe> {
  try {
    const res = await fetchImpl(`${baseUrl}/health`);
    if (!res.ok) {
      return { state: "error", message: `HTTP ${res.status}` };
    }
    const data = (await res.json()) as HealthResponse;
    return { state: "ok", data };
  } catch (err) {
    return {
      state: "error",
      message: err instanceof Error ? err.message : "Network unavailable",
    };
  }
}
