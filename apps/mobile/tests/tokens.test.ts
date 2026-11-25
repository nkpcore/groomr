import { describe, expect, it, vi } from "vitest";
import { IOS_TOUCH_TARGET_MIN_PT, MOBILE_THEME, TOUCH_TARGET_MIN_DP } from "../src/theme/tokens";
import { fetchMobileHealth } from "../src/services/health";

vi.mock("react-native", () => ({
  Platform: { OS: "web" },
}));

vi.mock("expo-secure-store", () => ({
  getItemAsync: vi.fn(async () => null),
  setItemAsync: vi.fn(async () => undefined),
  deleteItemAsync: vi.fn(async () => undefined),
}));

import { authorizedMobileRequest, MobileApiError } from "../src/services/authApi";
import {
  fetchBranchAvailability,
  fetchBranches,
  formatIstDateKey,
} from "../src/services/discoveryApi";

describe("mobile foundation, Phase 1 auth, and Phase 2 discovery invariants", () => {
  it("enforces accessible touch target floors and CHAIR palette", () => {
    expect(TOUCH_TARGET_MIN_DP).toBeGreaterThanOrEqual(48);
    expect(IOS_TOUCH_TARGET_MIN_PT).toBeGreaterThanOrEqual(44);
    expect(MOBILE_THEME.colors.ivoryCanvas).toBe("#FAF7F2");
    expect(MOBILE_THEME.colors.olivePrimary).toBe("#4A5D4E");
  });

  it("handles API health unreachable errors gracefully", async () => {
    const failingFetch = async () => {
      throw new Error("Connection refused");
    };
    const res = await fetchMobileHealth(failingFetch as unknown as typeof fetch);
    expect(res.state).toBe("error");
    if (res.state === "error") {
      expect(res.message).toContain("Connection refused");
    }
  });

  it("refreshes mobile session on 401 and surfaces 403 permission denial", async () => {
    const session = {
      accessToken: "old-token",
      refreshToken: "refresh-1",
      userId: "u1",
      roles: ["CUSTOMER"] as ["CUSTOMER"],
      preferredLocale: "en" as const,
    };

    let attempt = 0;
    const mockFetch = vi.fn(async (url: string) => {
      attempt += 1;
      if (url.endsWith("/users/me") && attempt === 1) {
        return new Response(
          JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Expired" } }),
          { status: 401 }
        );
      }
      if (url.endsWith("/auth/refresh")) {
        return Response.json({
          access_token: "new-token",
          refresh_token: "refresh-2",
          token_type: "bearer",
          expires_in_seconds: 1800,
          refresh_expires_in_seconds: 2592000,
          user_id: "u1",
          roles: ["CUSTOMER"],
          preferred_locale: "en",
        });
      }
      return Response.json({ id: "u1", full_name: "[DEMO] Kabir" });
    });

    const profile = await authorizedMobileRequest<{ id: string }>(
      "/users/me",
      session,
      {},
      undefined,
      mockFetch as unknown as typeof fetch,
      "http://localhost:8000/api/v1"
    );
    expect(profile.id).toBe("u1");

    const forbiddenFetch = vi.fn(async () => {
      return new Response(JSON.stringify({ error: { code: "FORBIDDEN", message: "Denied" } }), {
        status: 403,
      });
    });

    await expect(
      authorizedMobileRequest(
        "/admin/audit-logs",
        session,
        {},
        undefined,
        forbiddenFetch as unknown as typeof fetch,
        "http://localhost:8000/api/v1"
      )
    ).rejects.toBeInstanceOf(MobileApiError);
  });

  it("builds PostGIS branch query params and multi-service availability URLs cleanly", async () => {
    const capturedUrls: string[] = [];
    const mockFetch = vi.fn(async (url: string) => {
      capturedUrls.push(url);
      if (url.includes("/availability")) {
        return Response.json({
          branch_id: "b1",
          date: "2026-11-26",
          timezone: "Asia/Kolkata",
          online_booking_paused: false,
          is_branch_closed: false,
          slots: [],
        });
      }
      return Response.json({
        items: [],
        total_count: 0,
        verification_badge_disclaimer: "Independent verification",
      });
    });

    await fetchBranches(
      {
        lat: 12.9784,
        lng: 77.6408,
        radiusMeters: 5000,
        verifiedOnly: true,
        category: "HAIRCUT",
        maxPricePaise: 50000,
      },
      mockFetch as unknown as typeof fetch,
      "http://localhost:8000/api/v1"
    );

    expect(capturedUrls[0]).toContain("lat=12.9784");
    expect(capturedUrls[0]).toContain("verified_only=true");
    expect(capturedUrls[0]).toContain("category=HAIRCUT");
    expect(capturedUrls[0]).toContain("max_price_paise=50000");

    await fetchBranchAvailability(
      "b1",
      ["svc-1", "svc-2"],
      "2026-11-26",
      "staff-1",
      mockFetch as unknown as typeof fetch,
      "http://localhost:8000/api/v1"
    );

    expect(capturedUrls[1]).toContain("service_ids=svc-1");
    expect(capturedUrls[1]).toContain("service_ids=svc-2");
    expect(capturedUrls[1]).toContain("date=2026-11-26");
    expect(capturedUrls[1]).toContain("staff_id=staff-1");
    expect(formatIstDateKey(0, new Date("2026-11-25T20:00:00Z"))).toBe("2026-11-26");
  });
});
