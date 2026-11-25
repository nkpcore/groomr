"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, CheckCircle2, LogOut, RefreshCw, ShieldCheck, WifiOff } from "lucide-react";
import {
  getTranslations,
  type SupportedLocale,
  type UserProfileDto,
} from "@chair/shared-types";
import {
  ApiClientError,
  clearWebSession,
  fetchFoundationProbe,
  fetchMyProfile,
  loadWebSession,
  logoutSession,
  saveWebSession,
  sessionFromTokenResponse,
  type ApiProbeResult,
  type StoredWebSession,
} from "@/lib/api";
import { AccountConsentsPanel } from "@/components/AccountConsentsPanel";
import { OtpAuthCard } from "@/components/OtpAuthCard";
import { RoleWorkspacePanel } from "@/components/RoleWorkspacePanel";

interface ChairSurfaceShellProps {
  surfaceKey: "customer" | "partner" | "admin";
}

export function ChairSurfaceShell({ surfaceKey }: ChairSurfaceShellProps) {
  const [locale, setLocale] = useState<SupportedLocale>("en");
  const [probeLoading, setProbeLoading] = useState(true);
  const [probe, setProbe] = useState<ApiProbeResult | null>(null);

  const [session, setSession] = useState<StoredWebSession | null>(null);
  const [profile, setProfile] = useState<UserProfileDto | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<"offline" | "error" | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  const t = getTranslations(locale);

  const handleSessionUpdate = useCallback((next: StoredWebSession | null) => {
    setSession(next);
    if (!next) {
      setProfile(null);
    }
  }, []);

  const runProbe = useCallback(async () => {
    setProbeLoading(true);
    const result = await fetchFoundationProbe();
    setProbe(result);
    setProbeLoading(false);
  }, []);

  const hydrateProfile = useCallback(async (activeSession: StoredWebSession) => {
    setProfileLoading(true);
    setProfileError(null);
    try {
      const me = await fetchMyProfile(activeSession, handleSessionUpdate);
      setProfile(me);
      setLocale(me.preferred_locale);
    } catch (err) {
      if (err instanceof ApiClientError && (err.status === 401 || err.status === 403)) {
        clearWebSession();
        setSession(null);
        setProfile(null);
      } else if (err instanceof ApiClientError && err.code === "OFFLINE") {
        setProfileError("offline");
      } else {
        setProfileError("error");
      }
    } finally {
      setProfileLoading(false);
    }
  }, [handleSessionUpdate]);

  useEffect(() => {
    void runProbe();
    const existing = loadWebSession();
    if (existing) {
      setSession(existing);
      setLocale(existing.preferredLocale);
      void hydrateProfile(existing);
    }
  }, [hydrateProfile, runProbe]);

  function handleAuthenticated(tokens: Parameters<typeof sessionFromTokenResponse>[0]) {
    const nextSession = sessionFromTokenResponse(tokens);
    saveWebSession(nextSession);
    setSession(nextSession);
    setLocale(nextSession.preferredLocale);
    void hydrateProfile(nextSession);
  }

  async function handleSignOut() {
    if (!session) {
      return;
    }
    setSigningOut(true);
    try {
      await logoutSession(session);
    } catch {
      // Always clear UI state even if network/revoke call fails.
    } finally {
      setSession(null);
      setProfile(null);
      setProfileError(null);
      setSigningOut(false);
    }
  }

  const surfaceTitle = t.surfaces[surfaceKey];
  const navItems: Array<{ key: "customer" | "partner" | "admin"; href: string; label: string }> = [
    { key: "customer", href: "/", label: t.surfaces.customer },
    { key: "partner", href: "/partner", label: t.surfaces.partner },
    { key: "admin", href: "/admin", label: t.surfaces.admin },
  ];

  return (
    <div
      lang={locale}
      className="mx-auto flex min-h-screen max-w-5xl flex-col justify-between px-6 py-10"
    >
      <div>
        <a href="#main-content" className="skip-link visually-hidden">
          {t.health.skipToContent}
        </a>

        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[#E2DACD] pb-6">
          <h1
            className="text-3xl font-medium tracking-tight text-[#1C1B19]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            <span className="text-[#9C744F]">{t.brand.name}</span>
            <span aria-hidden="true" className="mx-2 text-[#E2DACD]">
              /
            </span>
            <span>{surfaceTitle}</span>
          </h1>

          <div className="flex flex-wrap items-center gap-3">
            {session ? (
              <button
                type="button"
                disabled={signingOut}
                onClick={() => void handleSignOut()}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-[#E2DACD] bg-[#F4EFE6] px-3.5 text-sm font-medium text-[#1C1B19] hover:border-[#9E3B33]"
              >
                <LogOut className="h-4 w-4 text-[#524E48]" aria-hidden="true" />
                <span>{signingOut ? t.auth.signingOut : t.auth.signOutButton}</span>
              </button>
            ) : null}

            <div className="flex items-center gap-2" role="group" aria-label={t.health.languageLabel}>
              <span className="text-xs font-medium text-[#524E48]">{t.health.languageLabel}:</span>
              {(["en", "hi"] as const).map((lang) => (
                <button
                  key={lang}
                  type="button"
                  aria-pressed={locale === lang}
                  onClick={() => setLocale(lang)}
                  className={`min-h-[44px] rounded-md border px-3 text-sm font-medium transition-colors ${
                    locale === lang
                      ? "border-[#4A5D4E] bg-[#4A5D4E] text-white"
                      : "border-[#E2DACD] bg-[#F4EFE6] text-[#1C1B19] hover:bg-[#EAE2D4]"
                  }`}
                >
                  {lang === "en" ? "EN" : "हिन्दी"}
                </button>
              ))}
            </div>
          </div>
        </header>

        <nav
          aria-label={t.health.primaryNavLabel}
          className="mt-6 flex flex-wrap gap-3 text-sm font-medium"
        >
          {navItems.map((item) => {
            const isCurrent = item.key === surfaceKey;
            return (
              <Link
                key={item.key}
                href={item.href}
                aria-current={isCurrent ? "page" : undefined}
                className={`inline-flex min-h-[44px] items-center rounded-md border px-4 transition-colors ${
                  isCurrent
                    ? "border-[#4A5D4E] bg-[#E7ECE8] text-[#1C1B19]"
                    : "border-[#E2DACD] bg-[#F4EFE6] text-[#1C1B19] hover:border-[#9C744F]"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <main id="main-content" tabIndex={-1} className="mt-8 space-y-6 outline-none">
          {!session ? (
            <OtpAuthCard t={t} onAuthenticated={handleAuthenticated} />
          ) : profileLoading && !profile ? (
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
          ) : profileError && !profile ? (
            <section
              role="alert"
              className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[#9E3B33]/35 bg-[#F9ECEA] p-6"
            >
              <div className="flex items-start gap-3">
                {profileError === "offline" ? (
                  <WifiOff className="mt-0.5 h-5 w-5 text-[#9C744F]" aria-hidden="true" />
                ) : (
                  <AlertCircle className="mt-0.5 h-5 w-5 text-[#9E3B33]" aria-hidden="true" />
                )}
                <p className="text-sm font-medium text-[#1C1B19]">
                  {profileError === "offline" ? t.states.offline : t.states.networkError}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void hydrateProfile(session)}
                className="min-h-[44px] rounded-md bg-[#1C1B19] px-4 text-sm font-medium text-white"
              >
                {t.health.retry}
              </button>
            </section>
          ) : profile ? (
            <>
              <RoleWorkspacePanel
                surfaceKey={surfaceKey}
                locale={locale}
                t={t}
                session={session}
                profile={profile}
                onSessionUpdate={handleSessionUpdate}
              />
              <AccountConsentsPanel
                t={t}
                session={session}
                profile={profile}
                onSessionUpdate={handleSessionUpdate}
                onProfileUpdate={setProfile}
                onLocaleChange={setLocale}
              />
            </>
          ) : null}

          <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-5">
            <p className="text-xs text-[#524E48]">{t.health.phaseNotice}</p>

            <div className="mt-3">
              {probeLoading && (
                <div className="flex items-center gap-2.5 text-sm text-[#524E48]">
                  <RefreshCw className="h-4 w-4 animate-spin text-[#4A5D4E]" aria-hidden="true" />
                  <span>{t.states.loading}</span>
                </div>
              )}

              {!probeLoading && probe?.state === "offline" && (
                <div
                  role="alert"
                  className="flex items-start gap-2.5 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3"
                >
                  <WifiOff className="mt-0.5 h-4 w-4 text-[#9C744F]" aria-hidden="true" />
                  <p className="text-sm text-[#1C1B19]">{t.states.offline}</p>
                </div>
              )}

              {!probeLoading && probe?.state === "error" && (
                <div
                  role="alert"
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-[#9E3B33]/30 bg-[#F9ECEA] p-3"
                >
                  <div className="flex items-start gap-2.5">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-[#9E3B33]" aria-hidden="true" />
                    <div>
                      <p className="text-sm font-medium text-[#1C1B19]">{t.states.error}</p>
                      {probe.message ? (
                        <p className="text-xs text-[#524E48]">{probe.message}</p>
                      ) : null}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void runProbe()}
                    className="min-h-[44px] rounded-md bg-[#1C1B19] px-4 text-xs font-medium text-white hover:bg-[#2D2B28]"
                  >
                    {t.health.retry}
                  </button>
                </div>
              )}

              {!probeLoading && probe?.state === "ok" && probe.health && (
                <div className="flex flex-wrap items-center justify-between gap-4" aria-live="polite">
                  <div className="flex flex-wrap items-center gap-4 text-sm">
                    <span className="inline-flex items-center gap-2 font-semibold text-[#1C1B19]">
                      <CheckCircle2 className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
                      {probe.health.status === "ok" ? t.health.statusOk : t.health.statusDegraded}
                    </span>
                    <span className="text-xs text-[#524E48]">
                      {t.health.database}: {probe.health.checks.database.status} · {t.health.postgis}:{" "}
                      {probe.health.checks.postgis.status} · {t.health.redis}:{" "}
                      {probe.health.checks.redis.status}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => void runProbe()}
                    className="min-h-[44px] rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-3.5 text-xs font-medium text-[#1C1B19] hover:border-[#4A5D4E]"
                  >
                    {t.health.retry}
                  </button>
                </div>
              )}
            </div>
          </section>
        </main>
      </div>

      <footer className="mt-10 flex items-start gap-2.5 border-t border-[#E2DACD] pt-5 text-xs text-[#524E48]">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#4A5D4E]" aria-hidden="true" />
        <p>
          <strong className="font-semibold text-[#1C1B19]">{t.brand.verifiedBadge}:</strong>{" "}
          {t.brand.verifiedDisclaimer}
        </p>
      </footer>
    </div>
  );
}
