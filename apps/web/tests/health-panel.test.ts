import { describe, expect, it } from "vitest";
import { fetchFoundationProbe } from "../src/lib/api";

describe("fetchFoundationProbe", () => {
  it("returns offline immediately when navigator is offline", async () => {
    const result = await fetchFoundationProbe(fetch, "http://localhost:8000/api/v1", false);
    expect(result).toEqual({ state: "offline" });
  });

  it("returns structured error on HTTP failure", async () => {
    const mockFetch = async () => new Response(null, { status: 503 });
    const result = await fetchFoundationProbe(
      mockFetch as unknown as typeof fetch,
      "http://localhost:8000/api/v1",
      true
    );
    expect(result.state).toBe("error");
    expect(result.message).toContain("503");
  });

  it("parses health and meta responses on success", async () => {
    const mockFetch = async (url: string) => {
      if (url.endsWith("/health")) {
        return Response.json({
          status: "ok",
          service: "chair-api",
          version: "0.1.0",
          environment: "test",
          timestamp_utc: "2026-11-25T00:00:00Z",
          booking_hold_ttl_seconds: 300,
          adapters: {
            auth_otp: "mock",
            payments: "test_mode",
            storage: "local_signed",
            maps: "local_stub",
            notifications: "console_outbox",
          },
          checks: {
            database: { status: "ok" },
            postgis: { status: "ok" },
            redis: { status: "ok" },
          },
        });
      }
      return Response.json({
        brand: "CHAIR",
        currency: "INR",
        supported_locales: ["en", "hi"],
        booking_hold_ttl_seconds: 300,
        verification_badge_disclaimer: "Independent verification",
      });
    };

    const result = await fetchFoundationProbe(
      mockFetch as unknown as typeof fetch,
      "http://localhost:8000/api/v1",
      true
    );
    expect(result.state).toBe("ok");
    expect(result.health?.booking_hold_ttl_seconds).toBe(300);
    expect(result.meta?.brand).toBe("CHAIR");
  });
});
