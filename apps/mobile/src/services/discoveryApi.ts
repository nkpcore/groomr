import type {
  AvailabilityResponseDto,
  BranchDetailResponseDto,
  BranchListResponseDto,
  ServiceCategory,
} from "@chair/shared-types";
import { getMobileApiBaseUrl } from "./health";
import { rawMobileJson } from "./http";

export interface BranchSearchParams {
  lat?: number | null;
  lng?: number | null;
  radiusMeters?: number;
  city?: string | null;
  q?: string | null;
  category?: ServiceCategory | null;
  maxPricePaise?: number | null;
  verifiedOnly?: boolean;
  openNow?: boolean;
  sort?: "distance" | "price_asc" | "rating" | "featured";
  limit?: number;
}

export function formatIstDateKey(offsetDays: number = 0, now: Date = new Date()): string {
  const istMs = now.getTime() + 330 * 60 * 1000 + offsetDays * 86_400_000;
  const d = new Date(istMs);
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function fetchBranches(
  params: BranchSearchParams = {},
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<BranchListResponseDto> {
  const qs = new URLSearchParams();
  if (params.lat != null && params.lng != null) {
    qs.set("lat", String(params.lat));
    qs.set("lng", String(params.lng));
    qs.set("radius_meters", String(params.radiusMeters ?? 10000));
  }
  if (params.city && params.city.trim()) {
    qs.set("city", params.city.trim());
  }
  if (params.q && params.q.trim()) {
    qs.set("q", params.q.trim());
  }
  if (params.category) {
    qs.set("category", params.category);
  }
  if (params.maxPricePaise != null) {
    qs.set("max_price_paise", String(params.maxPricePaise));
  }
  if (params.verifiedOnly) {
    qs.set("verified_only", "true");
  }
  if (params.openNow) {
    qs.set("open_now", "true");
  }
  if (params.sort) {
    qs.set("sort", params.sort);
  }
  qs.set("limit", String(params.limit ?? 20));

  const queryString = qs.toString();
  const suffix = queryString ? `?${queryString}` : "";
  return rawMobileJson<BranchListResponseDto>(`/branches${suffix}`, {}, fetchImpl, baseUrl);
}

export function fetchBranchDetail(
  branchId: string,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<BranchDetailResponseDto> {
  return rawMobileJson<BranchDetailResponseDto>(
    `/branches/${encodeURIComponent(branchId)}`,
    {},
    fetchImpl,
    baseUrl
  );
}

export function fetchBranchAvailability(
  branchId: string,
  serviceIds: string[],
  dateIso: string,
  staffId?: string | null,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = getMobileApiBaseUrl()
): Promise<AvailabilityResponseDto> {
  const qs = new URLSearchParams();
  for (const sid of serviceIds) {
    qs.append("service_ids", sid);
  }
  qs.set("date", dateIso);
  if (staffId) {
    qs.set("staff_id", staffId);
  }
  return rawMobileJson<AvailabilityResponseDto>(
    `/branches/${encodeURIComponent(branchId)}/availability?${qs.toString()}`,
    {},
    fetchImpl,
    baseUrl
  );
}
