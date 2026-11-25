import { describe, expect, it, vi } from "vitest";
import { ApiClientError, authorizedRequest, type StoredWebSession } from "../src/lib/api";

describe("web auth API client", () => {
  const initialSession: StoredWebSession = {
    accessToken: "expired-access-token",
    refreshToken: "valid-refresh-1",
    userId: "user-1",
    roles: ["CUSTOMER"],
    preferredLocale: "en",
  };

  it("rotates refresh token once on 401 and replays failed request", async () => {
    let callCount = 0;
    const mockFetch = vi.fn(async (url: string, init?: RequestInit) => {
      callCount += 1;
      if (url.endsWith("/users/me") && callCount === 1) {
        return new Response(
          JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Expired" } }),
          { status: 401 }
        );
      }
      if (url.endsWith("/auth/refresh")) {
        return Response.json({
          access_token: "fresh-access-token",
          refresh_token: "valid-refresh-2",
          token_type: "bearer",
          expires_in_seconds: 1800,
          refresh_expires_in_seconds: 2592000,
          user_id: "user-1",
          roles: ["CUSTOMER"],
          preferred_locale: "en",
        });
      }
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer fresh-access-token");
      return Response.json({ id: "user-1", phone_e164: "+919000000003" });
    });

    const onUpdate = vi.fn();
    const res = await authorizedRequest<{ id: string }>(
      "/users/me",
      initialSession,
      {},
      onUpdate,
      mockFetch as unknown as typeof fetch,
      "http://localhost:8000/api/v1"
    );

    expect(res.id).toBe("user-1");
    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it("preserves HTTP 403 permission error details cleanly", async () => {
    const mockFetch = vi.fn(async () => {
      return new Response(
        JSON.stringify({ error: { code: "FORBIDDEN", message: "Admin only" } }),
        { status: 403 }
      );
    });

    await expect(
      authorizedRequest(
        "/admin/audit-logs",
        initialSession,
        {},
        undefined,
        mockFetch as unknown as typeof fetch,
        "http://localhost:8000/api/v1"
      )
    ).rejects.toMatchObject({
      name: "ApiClientError",
      status: 403,
      code: "FORBIDDEN",
    } satisfies Partial<ApiClientError>);
  });
});
