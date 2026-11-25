import type { ApiErrorEnvelope } from "@chair/shared-types";
import { getMobileApiBaseUrl } from "./health";

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

export async function parseMobileError(res: Response): Promise<MobileApiError> {
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

export async function rawMobileJson<T>(
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
