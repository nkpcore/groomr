"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Building2, CheckCircle2, Lock, RefreshCw, ShieldAlert } from "lucide-react";
import type {
  AuditLogListResponseDto,
  BranchAccessResponseDto,
  PartnerContextResponseDto,
  TranslationCatalog,
  UserProfileDto,
} from "@chair/shared-types";
import {
  ApiClientError,
  fetchAdminAuditLogs,
  fetchPartnerBranchAccess,
  fetchPartnerContext,
  type StoredWebSession,
} from "@/lib/api";

interface RoleWorkspacePanelProps {
  surfaceKey: "customer" | "partner" | "admin";
  t: TranslationCatalog;
  session: StoredWebSession;
  profile: UserProfileDto;
  onSessionUpdate: (next: StoredWebSession | null) => void;
}

export function RoleWorkspacePanel({
  surfaceKey,
  t,
  session,
  profile,
  onSessionUpdate,
}: RoleWorkspacePanelProps) {
  const [loading, setLoading] = useState(surfaceKey !== "customer");
  const [errorCode, setErrorCode] = useState<"permission" | "offline" | "network" | "error" | null>(
    null
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [partnerData, setPartnerData] = useState<PartnerContextResponseDto | null>(null);
  const [branchProbe, setBranchProbe] = useState<Record<string, BranchAccessResponseDto | string>>(
    {}
  );
  const [auditData, setAuditData] = useState<AuditLogListResponseDto | null>(null);

  const loadRoleSurface = useCallback(async () => {
    if (surfaceKey === "customer") {
      setLoading(false);
      setErrorCode(null);
      return;
    }

    setLoading(true);
    setErrorCode(null);
    setErrorMessage(null);
    try {
      if (surfaceKey === "partner") {
        const res = await fetchPartnerContext(session, onSessionUpdate);
        setPartnerData(res);
      } else {
        const res = await fetchAdminAuditLogs(session, 20, onSessionUpdate);
        setAuditData(res);
      }
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.status === 403) {
          setErrorCode("permission");
          setErrorMessage(err.message);
        } else if (err.code === "OFFLINE") {
          setErrorCode("offline");
        } else if (err.code === "NETWORK_ERROR") {
          setErrorCode("network");
        } else {
          setErrorCode("error");
          setErrorMessage(err.message);
        }
      } else {
        setErrorCode("error");
      }
    } finally {
      setLoading(false);
    }
  }, [onSessionUpdate, session, surfaceKey]);

  useEffect(() => {
    void loadRoleSurface();
  }, [loadRoleSurface]);

  async function verifyBranch(branchId: string) {
    try {
      const access = await fetchPartnerBranchAccess(session, branchId, onSessionUpdate);
      setBranchProbe((prev) => ({ ...prev, [branchId]: access }));
    } catch (err) {
      const msg = err instanceof ApiClientError ? err.message : t.partner.accessDenied;
      setBranchProbe((prev) => ({ ...prev, [branchId]: msg }));
    }
  }

  if (surfaceKey === "customer") {
    return (
      <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-[#1C1B19]">
              {t.auth.signedInAs} {profile.full_name || profile.phone_e164}
            </p>
            <p className="mt-1 text-xs text-[#524E48]">
              {t.auth.activeRolesLabel}: {profile.roles.map((r) => r.role).join(", ")}
            </p>
          </div>
          <span className="rounded-md border border-[#4A5D4E]/30 bg-[#E7ECE8] px-3 py-1 text-xs font-medium text-[#1C1B19]">
            {profile.phone_e164}
          </span>
        </div>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
        <div className="flex items-center gap-3 text-sm text-[#524E48]">
          <RefreshCw className="h-4 w-4 animate-spin text-[#4A5D4E]" aria-hidden="true" />
          <span>{t.states.loading}</span>
        </div>
        <progress
          aria-label={t.states.loading}
          className="mt-3 h-1.5 w-full overflow-hidden rounded bg-[#E2DACD]"
        />
      </section>
    );
  }

  if (errorCode === "permission") {
    return (
      <section
        role="alert"
        className="rounded-lg border border-[#9E3B33]/35 bg-[#F9ECEA] p-6 text-[#1C1B19]"
      >
        <div className="flex items-start gap-3">
          <Lock className="mt-0.5 h-5 w-5 shrink-0 text-[#9E3B33]" aria-hidden="true" />
          <div>
            <p className="text-base font-semibold">{t.states.permissionDenied}</p>
            <p className="mt-1 text-sm text-[#524E48]">
              {surfaceKey === "partner"
                ? t.partner.permissionDeniedDetail
                : t.admin.permissionDeniedDetail}
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (errorCode === "offline" || errorCode === "network" || errorCode === "error") {
    return (
      <section
        role="alert"
        className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[#9E3B33]/35 bg-[#F9ECEA] p-6"
      >
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-5 w-5 text-[#9E3B33]" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-[#1C1B19]">
              {errorCode === "offline"
                ? t.states.offline
                : errorCode === "network"
                  ? t.states.networkError
                  : t.states.error}
            </p>
            {errorMessage ? <p className="mt-1 text-xs text-[#524E48]">{errorMessage}</p> : null}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadRoleSurface()}
          className="min-h-[44px] rounded-md bg-[#1C1B19] px-4 text-sm font-medium text-white"
        >
          {t.health.retry}
        </button>
      </section>
    );
  }

  if (surfaceKey === "partner" && partnerData) {
    return (
      <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
        <div className="flex items-center gap-2.5">
          <Building2 className="h-5 w-5 text-[#4A5D4E]" aria-hidden="true" />
          <h2
            className="text-lg font-medium text-[#1C1B19]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t.partner.workspaceHeading}
          </h2>
        </div>

        {partnerData.branches.length === 0 ? (
          <p className="mt-4 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 text-sm text-[#524E48]">
            {t.partner.emptyBranches}
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            {partnerData.branches.map((branch) => {
              const probeState = branchProbe[branch.id];
              return (
                <article
                  key={branch.id}
                  className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-base font-semibold text-[#1C1B19]">{branch.name}</h3>
                      <p className="mt-0.5 text-xs text-[#524E48]">
                        {branch.city}, {branch.state}
                      </p>
                    </div>
                    <span className="rounded bg-[#E7ECE8] px-2 py-0.5 text-xs font-medium text-[#1C1B19]">
                      {branch.verification_status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-[#524E48]">
                    {branch.online_booking_paused
                      ? t.partner.pausedLabel
                      : t.partner.activeLabel}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => void verifyBranch(branch.id)}
                      className="min-h-[44px] rounded-md border border-[#E2DACD] bg-[#F4EFE6] px-3.5 text-xs font-semibold text-[#1C1B19] hover:border-[#4A5D4E]"
                    >
                      {t.partner.checkBranchAccess}
                    </button>
                    {probeState && typeof probeState !== "string" ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#4A5D4E]">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                        {t.partner.accessGranted}
                      </span>
                    ) : typeof probeState === "string" ? (
                      <span className="text-xs text-[#9E3B33]">{probeState}</span>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <ShieldAlert className="h-5 w-5 text-[#4A5D4E]" aria-hidden="true" />
          <h2
            className="text-lg font-medium text-[#1C1B19]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t.admin.auditHeading}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => void loadRoleSurface()}
          className="min-h-[44px] rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-3.5 text-xs font-semibold text-[#1C1B19] hover:border-[#4A5D4E]"
        >
          {t.admin.refreshLogs}
        </button>
      </div>

      {!auditData || auditData.items.length === 0 ? (
        <p className="mt-4 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 text-sm text-[#524E48]">
          {t.admin.emptyLogs}
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-md border border-[#E2DACD] bg-[#FAF7F2]">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-[#E2DACD] text-[#524E48]">
                <th className="px-3 py-2.5 font-semibold">{t.admin.actionColumn}</th>
                <th className="px-3 py-2.5 font-semibold">{t.admin.actorRoleColumn}</th>
                <th className="px-3 py-2.5 font-semibold">{t.admin.resourceColumn}</th>
                <th className="px-3 py-2.5 font-semibold">{t.admin.timeColumn}</th>
              </tr>
            </thead>
            <tbody>
              {auditData.items.map((item) => (
                <tr key={item.id} className="border-b border-[#E2DACD]/60 last:border-b-0">
                  <td className="px-3 py-2.5 font-mono font-medium text-[#1C1B19]">
                    {item.action}
                  </td>
                  <td className="px-3 py-2.5 text-[#524E48]">{item.actor_role}</td>
                  <td className="px-3 py-2.5 text-[#524E48]">
                    {item.resource_type}:{item.resource_id.slice(0, 8)}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-[#524E48]">{item.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
