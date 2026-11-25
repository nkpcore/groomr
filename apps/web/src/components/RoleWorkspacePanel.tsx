"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Lock, RefreshCw } from "lucide-react";
import type {
  AdminVerificationsResponseDto,
  AuditLogListResponseDto,
  PartnerContextResponseDto,
  SupportedLocale,
  TranslationCatalog,
  UserProfileDto,
} from "@chair/shared-types";
import {
  ApiClientError,
  fetchAdminAuditLogs,
  fetchAdminVerifications,
  fetchPartnerContext,
  type StoredWebSession,
} from "@/lib/api";
import { AdminGovernanceWorkspace } from "@/components/AdminGovernanceWorkspace";
import { PartnerOnboardingCard } from "@/components/PartnerOnboardingCard";
import { PartnerWorkspace } from "@/components/PartnerWorkspace";

interface RoleWorkspacePanelProps {
  surfaceKey: "customer" | "partner" | "admin";
  locale: SupportedLocale;
  t: TranslationCatalog;
  session: StoredWebSession;
  profile: UserProfileDto;
  onSessionUpdate: (next: StoredWebSession | null) => void;
}

export function RoleWorkspacePanel({
  surfaceKey,
  locale,
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
  const [auditData, setAuditData] = useState<AuditLogListResponseDto | null>(null);
  const [verificationsData, setVerificationsData] = useState<AdminVerificationsResponseDto | null>(
    null
  );

  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const loadRoleSurface = useCallback(async () => {
    if (surfaceKey === "customer") {
      setLoading(false);
      setErrorCode(null);
      return;
    }

    setLoading(true);
    setErrorCode(null);
    setErrorMessage(null);
    const activeSession = sessionRef.current;
    try {
      if (surfaceKey === "partner") {
        const res = await fetchPartnerContext(activeSession, onSessionUpdate);
        setPartnerData(res);
      } else {
        const [auditRes, verificationsRes] = await Promise.all([
          fetchAdminAuditLogs(activeSession, 20, onSessionUpdate),
          fetchAdminVerifications(activeSession, onSessionUpdate),
        ]);
        setAuditData(auditRes);
        setVerificationsData(verificationsRes);
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
  }, [onSessionUpdate, surfaceKey]);

  useEffect(() => {
    void loadRoleSurface();
  }, [loadRoleSurface, session.userId]);

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

  if (loading && !partnerData && !auditData && !verificationsData) {
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
      <div className="space-y-6">
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
        {surfaceKey === "partner" ? (
          <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
            <PartnerOnboardingCard
              t={t}
              session={session}
              onSessionUpdate={onSessionUpdate}
              onOnboarded={async () => {
                await loadRoleSurface();
              }}
            />
          </section>
        ) : null}
      </div>
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
      <PartnerWorkspace
        t={t}
        locale={locale}
        session={session}
        partnerData={partnerData}
        onSessionUpdate={onSessionUpdate}
        onRefreshContext={loadRoleSurface}
      />
    );
  }

  return (
    <AdminGovernanceWorkspace
      t={t}
      session={session}
      auditData={auditData}
      verificationsData={verificationsData}
      onSessionUpdate={onSessionUpdate}
      onRefreshAll={loadRoleSurface}
    />
  );
}
