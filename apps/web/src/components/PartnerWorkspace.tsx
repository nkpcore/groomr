"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  CalendarClock,
  CheckCircle2,
  FileCheck2,
  PauseCircle,
  PlayCircle,
  Plus,
  Scissors,
  Trash2,
  UserCheck,
} from "lucide-react";
import { PartnerOnboardingCard } from "@/components/PartnerOnboardingCard";
import { SignedAssetDialog } from "@/components/SignedAssetDialog";
import {
  formatINRFromPaise,
  formatIstDateTime,
  type BookingDetailDto,
  type BranchAccessResponseDto,
  type BranchSetupStateDto,
  type DocumentType,
  type PartnerContextResponseDto,
  type ResourceType,
  type ScheduleBlockType,
  type SupportedLocale,
  type TranslationCatalog,
  type WalkInItemDto,
} from "@chair/shared-types";
import {
  ApiClientError,
  createPartnerBranchService,
  createPartnerResource,
  createPartnerScheduleBlock,
  createPartnerStaff,
  createPartnerWalkIn,
  deletePartnerScheduleBlock,
  fetchPartnerBranchAccess,
  fetchPartnerBranchBookings,
  fetchPartnerBranchSetup,
  fetchPartnerWalkIns,
  fetchSignedPrivateAsset,
  partnerTransitionBooking,
  togglePartnerBranchPause,
  updatePartnerBranchHours,
  updatePartnerBranchService,
  updatePartnerWalkIn,
  uploadPartnerDocument,
  type StoredWebSession,
} from "@/lib/api";

interface PartnerWorkspaceProps {
  t: TranslationCatalog;
  locale: SupportedLocale;
  session: StoredWebSession;
  partnerData: PartnerContextResponseDto;
  onSessionUpdate: (next: StoredWebSession | null) => void;
  onRefreshContext: () => Promise<void>;
}

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export function PartnerWorkspace({
  t,
  locale,
  session,
  partnerData,
  onSessionUpdate,
  onRefreshContext,
}: PartnerWorkspaceProps) {
  const [selectedBranchId, setSelectedBranchId] = useState<string>(
    () => partnerData.branches[0]?.id ?? ""
  );
  const [activeTab, setActiveTab] = useState<"desk" | "setup" | "kyc">(() =>
    partnerData.branches.length === 0 ? "kyc" : "desk"
  );
  const [branchProbe, setBranchProbe] = useState<Record<string, BranchAccessResponseDto | string>>(
    {}
  );
  const [setup, setSetup] = useState<BranchSetupStateDto | null>(null);
  const [bookings, setBookings] = useState<BookingDetailDto[]>([]);
  const [walkIns, setWalkIns] = useState<WalkInItemDto[]>([]);
  const [loadingBranch, setLoadingBranch] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Live Desk form states
  const [otpInputs, setOtpInputs] = useState<Record<string, string>>({});
  const [walkInName, setWalkInName] = useState("");
  const [walkInPhone, setWalkInPhone] = useState("");
  const [walkInSummary, setWalkInSummary] = useState("");
  const [walkInRupees, setWalkInRupees] = useState("299");
  const [walkInMinutes, setWalkInMinutes] = useState("30");
  const [walkInStaffChoices, setWalkInStaffChoices] = useState<Record<string, string>>({});
  const [walkInChairChoices, setWalkInChairChoices] = useState<Record<string, string>>({});

  // Shop Setup form states
  const [hoursDraft, setHoursDraft] = useState<
    Record<string, { open: string; close: string } | null>
  >({});
  const [catalogServiceId, setCatalogServiceId] = useState("");
  const [svcNameEn, setSvcNameEn] = useState("");
  const [svcNameHi, setSvcNameHi] = useState("");
  const [svcPriceRupees, setSvcPriceRupees] = useState("399");
  const [svcDuration, setSvcDuration] = useState("30");

  const [staffName, setStaffName] = useState("");
  const [staffBio, setStaffBio] = useState("");
  const [staffServiceIds, setStaffServiceIds] = useState<string[]>([]);
  const [shiftStart, setShiftStart] = useState("09:30");
  const [shiftEnd, setShiftEnd] = useState("21:00");

  const [blockType, setBlockType] = useState<ScheduleBlockType>("BREAK");
  const [blockStaffId, setBlockStaffId] = useState("");
  const [blockStartLocal, setBlockStartLocal] = useState("");
  const [blockEndLocal, setBlockEndLocal] = useState("");
  const [blockReason, setBlockReason] = useState("");

  const [chairName, setChairName] = useState("");
  const [chairType, setChairType] = useState<ResourceType>("BARBER_CHAIR");

  const [docType, setDocType] = useState<DocumentType>("SHOP_ESTABLISHMENT_LICENSE");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewAsset, setPreviewAsset] = useState<{ blobUrl: string; mimeType: string } | null>(
    null
  );

  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    if (!selectedBranchId && partnerData.branches[0]?.id) {
      setSelectedBranchId(partnerData.branches[0].id);
    }
  }, [partnerData.branches, selectedBranchId]);

  useEffect(() => {
    return () => {
      if (previewAsset) {
        URL.revokeObjectURL(previewAsset.blobUrl);
      }
    };
  }, [previewAsset]);

  const loadSelectedBranchData = useCallback(
    async (branchId: string) => {
      if (!branchId) {
        return;
      }
      setLoadingBranch(true);
      setActionError(null);
      const activeSession = sessionRef.current;
      try {
        const [setupRes, bookingsRes, walkInsRes] = await Promise.all([
          fetchPartnerBranchSetup(activeSession, branchId, onSessionUpdate),
          fetchPartnerBranchBookings(activeSession, branchId, onSessionUpdate),
          fetchPartnerWalkIns(activeSession, branchId, onSessionUpdate),
        ]);
        setSetup(setupRes);
        setHoursDraft(setupRes.branch.operating_hours_json || {});
        setCatalogServiceId((prev) =>
          setupRes.catalog_services.some((s) => s.id === prev)
            ? prev
            : (setupRes.catalog_services[0]?.id ?? "")
        );
        setStaffServiceIds((prev) => {
          const valid = prev.filter((id) => setupRes.branch_services.some((bs) => bs.id === id));
          if (valid.length > 0) {
            return valid;
          }
          return setupRes.branch_services.map((bs) => bs.id);
        });
        setBookings(bookingsRes.items);
        setWalkIns(walkInsRes.items);
      } catch (err) {
        setActionError(err instanceof ApiClientError ? err.message : t.states.error);
      } finally {
        setLoadingBranch(false);
      }
    },
    [onSessionUpdate, t.states.error]
  );

  useEffect(() => {
    setBlockStaffId("");
    setOtpInputs({});
    setWalkInStaffChoices({});
    setWalkInChairChoices({});
    if (selectedBranchId) {
      void loadSelectedBranchData(selectedBranchId);
    }
  }, [loadSelectedBranchData, selectedBranchId]);

  const selectedBranchSummary = useMemo(
    () => partnerData.branches.find((b) => b.id === selectedBranchId) ?? null,
    [partnerData.branches, selectedBranchId]
  );

  async function verifyBranch(branchId: string) {
    try {
      const access = await fetchPartnerBranchAccess(session, branchId, onSessionUpdate);
      setBranchProbe((prev) => ({ ...prev, [branchId]: access }));
    } catch (err) {
      const msg = err instanceof ApiClientError ? err.message : t.partner.accessDenied;
      setBranchProbe((prev) => ({ ...prev, [branchId]: msg }));
    }
  }

  async function runMutation(
    fn: () => Promise<string | void>,
    successMessage?: string
  ) {
    setSubmitting(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const nextBranchId = await fn();
      const targetBranchId = typeof nextBranchId === "string" ? nextBranchId : selectedBranchId;
      if (targetBranchId) {
        await loadSelectedBranchData(targetBranchId);
      }
      await onRefreshContext();
      if (successMessage) {
        setActionNotice(successMessage);
      }
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : t.states.error);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUploadDocument(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedBranchId || !selectedFile) {
      return;
    }
    if (selectedFile.size > MAX_UPLOAD_BYTES) {
      setActionError(t.partner.fileTooLargeError);
      return;
    }
    const contentBase64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = typeof reader.result === "string" ? reader.result : "";
        const comma = result.indexOf(",");
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      reader.onerror = () => reject(new Error("File read failed"));
      reader.readAsDataURL(selectedFile);
    });
    await runMutation(async () => {
      await uploadPartnerDocument(
        session,
        selectedBranchId,
        {
          document_type: docType,
          mime_type: selectedFile.type || "application/octet-stream",
          content_base64: contentBase64,
        },
        onSessionUpdate
      );
      setSelectedFile(null);
    }, t.partner.savedNotice);
  }

  async function openSignedPreview(signedUrl: string) {
    setActionError(null);
    try {
      if (previewAsset) {
        URL.revokeObjectURL(previewAsset.blobUrl);
      }
      const next = await fetchSignedPrivateAsset(session, signedUrl, onSessionUpdate);
      setPreviewAsset(next);
    } catch {
      setActionError(t.partner.signedDownloadError);
    }
  }

  return (
    <div className="space-y-6">
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
              const isSelected = branch.id === selectedBranchId;
              return (
                <article
                  key={branch.id}
                  className={`rounded-md border p-4 transition ${
                    isSelected
                      ? "border-[#4A5D4E] bg-[#FAF7F2] ring-1 ring-[#4A5D4E]/30"
                      : "border-[#E2DACD] bg-[#FAF7F2]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setSelectedBranchId(branch.id)}
                      className="min-h-[44px] text-left"
                    >
                      <h3 className="text-base font-semibold text-[#1C1B19]">{branch.name}</h3>
                      <p className="mt-0.5 text-xs text-[#524E48]">
                        {branch.city}, {branch.state} · {branch.status}
                      </p>
                    </button>
                    <span className="rounded bg-[#E7ECE8] px-2 py-0.5 text-xs font-medium text-[#1C1B19]">
                      {branch.verification_status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-[#524E48]">
                    {branch.online_booking_paused ? t.partner.pausedLabel : t.partner.activeLabel}
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

      {actionError ? (
        <div role="alert" className="rounded-md border border-[#9E3B33]/35 bg-[#F9ECEA] p-3 text-sm text-[#1C1B19]">
          {actionError}
        </div>
      ) : null}
      {actionNotice ? (
        <div role="status" className="rounded-md border border-[#4A5D4E]/35 bg-[#E7ECE8] p-3 text-sm text-[#1C1B19]">
          {actionNotice}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2" role="tablist" aria-label={t.partner.workspaceHeading}>
        {(
          [
            { id: "desk", label: t.partner.tabLiveDesk },
            { id: "setup", label: t.partner.tabShopSetup },
            { id: "kyc", label: t.partner.tabOnboardingKyc },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`min-h-[44px] rounded-md border px-4 text-sm font-medium ${
              activeTab === tab.id
                ? "border-[#1C1B19] bg-[#1C1B19] text-[#FAF7F2]"
                : "border-[#E2DACD] bg-[#F4EFE6] text-[#1C1B19] hover:border-[#4A5D4E]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "desk" && selectedBranchSummary ? (
        <section className="space-y-6 rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#E2DACD] pb-4">
            <div>
              <h3 className="text-base font-semibold text-[#1C1B19]">
                {t.partner.tabLiveDesk} · {selectedBranchSummary.city}
              </h3>
              <p className="text-xs text-[#524E48]">
                {selectedBranchSummary.online_booking_paused
                  ? t.partner.pausedLabel
                  : t.partner.activeLabel}
              </p>
            </div>
            <button
              type="button"
              disabled={submitting}
              onClick={() =>
                void runMutation(
                  async () => {
                    await togglePartnerBranchPause(
                      session,
                      selectedBranchSummary.id,
                      !selectedBranchSummary.online_booking_paused,
                      onSessionUpdate
                    );
                  },
                  t.partner.pauseStatusUpdated
                )
              }
              className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-[#1C1B19] bg-[#FAF7F2] px-4 text-xs font-semibold text-[#1C1B19] hover:bg-[#E7ECE8] disabled:opacity-50"
            >
              {selectedBranchSummary.online_booking_paused ? (
                <>
                  <PlayCircle className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
                  {t.partner.resumeBookingsBtn}
                </>
              ) : (
                <>
                  <PauseCircle className="h-4 w-4 text-[#9C744F]" aria-hidden="true" />
                  {t.partner.pauseBookingsBtn}
                </>
              )}
            </button>
          </div>

          <div>
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#1C1B19]">
              <CalendarClock className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
              {t.partner.bookingsHeading}
            </h4>
            {loadingBranch ? (
              <p className="text-xs text-[#524E48]">{t.states.loading}</p>
            ) : bookings.length === 0 ? (
              <p className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 text-xs text-[#524E48]">
                {t.partner.emptyBookings}
              </p>
            ) : (
              <div className="space-y-3">
                {bookings.map((booking) => (
                  <article
                    key={booking.id}
                    className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-mono text-xs font-semibold text-[#1C1B19]">
                          {booking.booking_code}
                        </span>
                        <span className="ml-2 rounded bg-[#E7ECE8] px-2 py-0.5 text-xs font-medium text-[#1C1B19]">
                          {booking.status}
                        </span>
                      </div>
                      <span className="text-xs font-medium text-[#1C1B19]">
                        {formatINRFromPaise(booking.net_payable_paise)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-[#524E48]">
                      {booking.items.map((item) => item.service_name_snapshot).join(", ")} ·{" "}
                      {formatIstDateTime(booking.scheduled_start_at, locale)}
                    </p>

                    {(booking.status === "CONFIRMED" ||
                      booking.status === "CHECKED_IN" ||
                      booking.status === "IN_SERVICE") && (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {(booking.status === "CONFIRMED" || booking.status === "IN_SERVICE") && (
                          <input
                            type="text"
                            inputMode="numeric"
                            maxLength={6}
                            value={otpInputs[booking.id] ?? ""}
                            onChange={(e) =>
                              setOtpInputs((prev) => ({
                                ...prev,
                                [booking.id]: e.target.value.replace(/\D/g, ""),
                              }))
                            }
                            placeholder={t.partner.otpPlaceholder}
                            aria-label={`${t.partner.otpPlaceholder} ${booking.booking_code}`}
                            className="min-h-[44px] w-40 rounded-md border border-[#E2DACD] bg-white px-3 font-mono text-sm text-[#1C1B19]"
                          />
                        )}
                        {booking.status === "CONFIRMED" && (
                          <>
                            <button
                              type="button"
                              disabled={submitting || (otpInputs[booking.id]?.length ?? 0) !== 6}
                              onClick={() =>
                                void runMutation(async () => {
                                  await partnerTransitionBooking(
                                    session,
                                    selectedBranchSummary.id,
                                    booking.id,
                                    "check-in",
                                    { otp_code: otpInputs[booking.id] },
                                    onSessionUpdate
                                  );
                                  setOtpInputs((prev) => ({ ...prev, [booking.id]: "" }));
                                })
                              }
                              className="min-h-[44px] rounded-md bg-[#4A5D4E] px-3 text-xs font-semibold text-white disabled:opacity-50"
                            >
                              {t.partner.verifyCheckInBtn}
                            </button>
                            <button
                              type="button"
                              disabled={submitting}
                              onClick={() =>
                                void runMutation(async () => {
                                  await partnerTransitionBooking(
                                    session,
                                    selectedBranchSummary.id,
                                    booking.id,
                                    "no-show",
                                    {},
                                    onSessionUpdate
                                  );
                                })
                              }
                              className="min-h-[44px] rounded-md border border-[#E2DACD] bg-[#F4EFE6] px-3 text-xs font-semibold text-[#1C1B19]"
                            >
                              {t.partner.noShowBtn}
                            </button>
                            <button
                              type="button"
                              disabled={submitting}
                              onClick={() =>
                                void runMutation(async () => {
                                  await partnerTransitionBooking(
                                    session,
                                    selectedBranchSummary.id,
                                    booking.id,
                                    "cancel",
                                    { reason: "Cancelled by partner desk" },
                                    onSessionUpdate
                                  );
                                })
                              }
                              className="min-h-[44px] rounded-md border border-[#9E3B33]/40 bg-[#F9ECEA] px-3 text-xs font-semibold text-[#9E3B33]"
                            >
                              {t.partner.cancelBookingBtn}
                            </button>
                          </>
                        )}
                        {booking.status === "CHECKED_IN" && (
                          <button
                            type="button"
                            disabled={submitting}
                            onClick={() =>
                              void runMutation(async () => {
                                await partnerTransitionBooking(
                                  session,
                                  selectedBranchSummary.id,
                                  booking.id,
                                  "start",
                                  {},
                                  onSessionUpdate
                                );
                              })
                            }
                            className="min-h-[44px] rounded-md bg-[#4A5D4E] px-3 text-xs font-semibold text-white"
                          >
                            {t.partner.startServiceBtn}
                          </button>
                        )}
                        {booking.status === "IN_SERVICE" && (
                          <button
                            type="button"
                            disabled={submitting || (otpInputs[booking.id]?.length ?? 0) !== 6}
                              onClick={() =>
                                void runMutation(async () => {
                                  await partnerTransitionBooking(
                                    session,
                                    selectedBranchSummary.id,
                                    booking.id,
                                    "complete",
                                    { otp_code: otpInputs[booking.id] },
                                    onSessionUpdate
                                  );
                                  setOtpInputs((prev) => ({ ...prev, [booking.id]: "" }));
                                })
                              }
                            className="min-h-[44px] rounded-md bg-[#1C1B19] px-3 text-xs font-semibold text-white disabled:opacity-50"
                          >
                            {t.partner.verifyCompleteBtn}
                          </button>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-[#E2DACD] pt-5">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#1C1B19]">
              <UserCheck className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
              {t.partner.walkInsHeading}
            </h4>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!walkInName.trim() || !walkInSummary.trim()) {
                  return;
                }
                const rupees = Number.parseInt(walkInRupees || "0", 10);
                const mins = Number.parseInt(walkInMinutes || "30", 10);
                void runMutation(async () => {
                  await createPartnerWalkIn(
                    session,
                    selectedBranchSummary.id,
                    {
                      customer_name: walkInName.trim(),
                      customer_phone_e164: walkInPhone.trim() || null,
                      service_summary: walkInSummary.trim(),
                      quoted_price_paise: Math.max(0, rupees) * 100,
                      estimated_duration_minutes: Math.max(5, mins),
                    },
                    onSessionUpdate
                  );
                  setWalkInName("");
                  setWalkInPhone("");
                  setWalkInSummary("");
                }, t.partner.savedNotice);
              }}
              className="grid grid-cols-1 gap-3 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 sm:grid-cols-2 lg:grid-cols-5"
            >
              <input
                type="text"
                required
                value={walkInName}
                onChange={(e) => setWalkInName(e.target.value)}
                placeholder={t.partner.guestNameLabel}
                aria-label={t.partner.guestNameLabel}
                className="min-h-[44px] rounded-md border border-[#E2DACD] bg-white px-3 text-xs text-[#1C1B19]"
              />
              <input
                type="tel"
                value={walkInPhone}
                onChange={(e) => setWalkInPhone(e.target.value)}
                placeholder={t.partner.guestPhoneLabel}
                aria-label={t.partner.guestPhoneLabel}
                className="min-h-[44px] rounded-md border border-[#E2DACD] bg-white px-3 text-xs text-[#1C1B19]"
              />
              <input
                type="text"
                required
                value={walkInSummary}
                onChange={(e) => setWalkInSummary(e.target.value)}
                placeholder={t.partner.walkInServiceLabel}
                aria-label={t.partner.walkInServiceLabel}
                className="min-h-[44px] rounded-md border border-[#E2DACD] bg-white px-3 text-xs text-[#1C1B19]"
              />
              <div className="flex gap-2">
                <input
                  type="number"
                  min={0}
                  value={walkInRupees}
                  onChange={(e) => setWalkInRupees(e.target.value)}
                  aria-label={t.partner.walkInPriceRupeesLabel}
                  className="min-h-[44px] w-1/2 rounded-md border border-[#E2DACD] bg-white px-2 text-xs text-[#1C1B19]"
                />
                <input
                  type="number"
                  min={5}
                  value={walkInMinutes}
                  onChange={(e) => setWalkInMinutes(e.target.value)}
                  aria-label={t.partner.walkInDurationLabel}
                  className="min-h-[44px] w-1/2 rounded-md border border-[#E2DACD] bg-white px-2 text-xs text-[#1C1B19]"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-md bg-[#1C1B19] px-3 text-xs font-semibold text-white"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                {t.partner.addWalkInBtn}
              </button>
            </form>

            {walkIns.length === 0 ? (
              <p className="mt-3 text-xs text-[#524E48]">{t.partner.emptyWalkIns}</p>
            ) : (
              <div className="mt-3 space-y-2">
                {walkIns.map((w) => (
                  <div
                    key={w.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-4 py-3 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-[#1C1B19]">
                        #{w.queue_position} {w.customer_name}
                      </span>
                      <span className="ml-2 text-[#524E48]">
                        {w.service_summary} · {formatINRFromPaise(w.quoted_price_paise)} ·{" "}
                        {w.status}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {w.status === "WAITING" && (
                        <>
                          {setup && setup.staff.some((st) => st.status === "ACTIVE") ? (
                            <select
                              value={
                                walkInStaffChoices[w.id] ??
                                w.staff_id ??
                                setup.staff.find((st) => st.status === "ACTIVE")?.id ??
                                ""
                              }
                              onChange={(e) =>
                                setWalkInStaffChoices((prev) => ({
                                  ...prev,
                                  [w.id]: e.target.value,
                                }))
                              }
                              aria-label={`${t.partner.staffNameLabel} ${w.customer_name}`}
                              className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs text-[#1C1B19]"
                            >
                              {setup.staff
                                .filter((st) => st.status === "ACTIVE")
                                .map((st) => (
                                  <option key={st.id} value={st.id}>
                                    {st.display_name}
                                  </option>
                                ))}
                            </select>
                          ) : null}
                          {setup && setup.resources.some((r) => r.is_active) ? (
                            <select
                              value={
                                walkInChairChoices[w.id] ??
                                w.resource_id ??
                                setup.resources.find((r) => r.is_active)?.id ??
                                ""
                              }
                              onChange={(e) =>
                                setWalkInChairChoices((prev) => ({
                                  ...prev,
                                  [w.id]: e.target.value,
                                }))
                              }
                              aria-label={`${t.partner.chairNameLabel} ${w.customer_name}`}
                              className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs text-[#1C1B19]"
                            >
                              {setup.resources
                                .filter((res) => res.is_active)
                                .map((res) => (
                                  <option key={res.id} value={res.id}>
                                    {res.name}
                                  </option>
                                ))}
                            </select>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => {
                              const activeStaffId =
                                walkInStaffChoices[w.id] ??
                                w.staff_id ??
                                setup?.staff.find((st) => st.status === "ACTIVE")?.id ??
                                null;
                              const activeChairId =
                                walkInChairChoices[w.id] ??
                                w.resource_id ??
                                setup?.resources.find((r) => r.is_active)?.id ??
                                null;
                              void runMutation(async () => {
                                await updatePartnerWalkIn(
                                  session,
                                  selectedBranchSummary.id,
                                  w.id,
                                  {
                                    status: "SEATED",
                                    staff_id: activeStaffId,
                                    resource_id: activeChairId,
                                  },
                                  onSessionUpdate
                                );
                              });
                            }}
                            className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 font-semibold text-[#1C1B19]"
                          >
                            {t.partner.seatGuestBtn}
                          </button>
                        </>
                      )}
                      {w.status === "SEATED" && (
                        <button
                          type="button"
                          onClick={() =>
                            void runMutation(async () => {
                              await updatePartnerWalkIn(
                                session,
                                selectedBranchSummary.id,
                                w.id,
                                { status: "IN_SERVICE" },
                                onSessionUpdate
                              );
                            })
                          }
                          className="min-h-[44px] rounded bg-[#4A5D4E] px-3 font-semibold text-white"
                        >
                          {t.partner.startWalkInBtn}
                        </button>
                      )}
                      {(w.status === "SEATED" || w.status === "IN_SERVICE") && (
                        <button
                          type="button"
                          onClick={() =>
                            void runMutation(async () => {
                              await updatePartnerWalkIn(
                                session,
                                selectedBranchSummary.id,
                                w.id,
                                { status: "COMPLETED" },
                                onSessionUpdate
                              );
                            })
                          }
                          className="min-h-[44px] rounded bg-[#1C1B19] px-3 font-semibold text-white"
                        >
                          {t.partner.completeWalkInBtn}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      ) : null}

      {activeTab === "setup" && setup ? (
        <section className="space-y-6 rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
          <div>
            <h3 className="mb-3 text-base font-semibold text-[#1C1B19]">{t.partner.hoursHeading}</h3>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {WEEKDAYS.map((day) => {
                const win = hoursDraft[day] ?? null;
                return (
                  <div
                    key={day}
                    className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold uppercase text-[#1C1B19]">{day}</span>
                      <button
                        type="button"
                        onClick={() =>
                          setHoursDraft((prev) => ({
                            ...prev,
                            [day]: win ? null : { open: "09:30", close: "21:30" },
                          }))
                        }
                        className="min-h-[44px] px-2 text-xs font-medium text-[#4A5D4E] underline"
                      >
                        {win ? t.partner.closedDayLabel : "09:30–21:30"}
                      </button>
                    </div>
                    {win ? (
                      <div className="mt-2 flex items-center gap-1.5">
                        <input
                          type="time"
                          value={win.open}
                          aria-label={`${day} open`}
                          onChange={(e) =>
                            setHoursDraft((prev) => ({
                              ...prev,
                              [day]: { open: e.target.value, close: win.close },
                            }))
                          }
                          className="min-h-[44px] w-1/2 rounded border border-[#E2DACD] bg-white px-2 text-[#1C1B19]"
                        />
                        <input
                          type="time"
                          value={win.close}
                          aria-label={`${day} close`}
                          onChange={(e) =>
                            setHoursDraft((prev) => ({
                              ...prev,
                              [day]: { open: win.open, close: e.target.value },
                            }))
                          }
                          className="min-h-[44px] w-1/2 rounded border border-[#E2DACD] bg-white px-2 text-[#1C1B19]"
                        />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <button
              type="button"
              disabled={submitting}
              onClick={() =>
                void runMutation(async () => {
                  await updatePartnerBranchHours(
                    session,
                    setup.branch.id,
                    hoursDraft,
                    onSessionUpdate
                  );
                }, t.partner.savedNotice)
              }
              className="mt-3 min-h-[44px] rounded-md bg-[#1C1B19] px-4 text-xs font-semibold text-white"
            >
              {t.partner.saveHoursBtn}
            </button>
          </div>

          <div className="border-t border-[#E2DACD] pt-5">
            <h3 className="mb-3 flex items-center gap-2 text-base font-semibold text-[#1C1B19]">
              <Scissors className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
              {t.partner.servicesHeading}
            </h3>
            <div className="space-y-2">
              {setup.branch_services.map((bs) => (
                <div
                  key={bs.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-4 py-2.5 text-xs"
                >
                  <div>
                    <span className="font-semibold text-[#1C1B19]">{bs.display_name_en}</span>{" "}
                    <span className="text-[#524E48]">
                      ({bs.display_name_hi}) · {formatINRFromPaise(bs.price_paise)} ·{" "}
                      {bs.duration_minutes}m
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      void runMutation(async () => {
                        await updatePartnerBranchService(
                          session,
                          setup.branch.id,
                          bs.id,
                          { is_active: !bs.is_active },
                          onSessionUpdate
                        );
                      })
                    }
                    className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 font-semibold text-[#1C1B19]"
                  >
                    {bs.is_active ? t.partner.deactivateBtn : t.partner.activateBtn}
                  </button>
                </div>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!catalogServiceId || !svcNameEn.trim() || !svcNameHi.trim()) {
                  return;
                }
                void runMutation(async () => {
                  await createPartnerBranchService(
                    session,
                    setup.branch.id,
                    {
                      service_id: catalogServiceId,
                      display_name_en: svcNameEn.trim(),
                      display_name_hi: svcNameHi.trim(),
                      price_paise: Math.max(0, Number.parseInt(svcPriceRupees || "0", 10)) * 100,
                      duration_minutes: Math.max(5, Number.parseInt(svcDuration || "30", 10)),
                    },
                    onSessionUpdate
                  );
                  setSvcNameEn("");
                  setSvcNameHi("");
                }, t.partner.savedNotice);
              }}
              className="mt-3 grid grid-cols-1 gap-2 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3 sm:grid-cols-2 lg:grid-cols-6"
            >
              <select
                value={catalogServiceId}
                onChange={(e) => setCatalogServiceId(e.target.value)}
                aria-label={t.partner.catalogServiceLabel}
                className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs text-[#1C1B19]"
              >
                {setup.catalog_services.map((svc) => (
                  <option key={svc.id} value={svc.id}>
                    {svc.name_en} ({svc.category})
                  </option>
                ))}
              </select>
              <input
                type="text"
                required
                value={svcNameEn}
                onChange={(e) => setSvcNameEn(e.target.value)}
                placeholder={t.partner.serviceNameEnLabel}
                aria-label={t.partner.serviceNameEnLabel}
                className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
              />
              <input
                type="text"
                required
                value={svcNameHi}
                onChange={(e) => setSvcNameHi(e.target.value)}
                placeholder={t.partner.serviceNameHiLabel}
                aria-label={t.partner.serviceNameHiLabel}
                className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
              />
              <input
                type="number"
                min={0}
                value={svcPriceRupees}
                onChange={(e) => setSvcPriceRupees(e.target.value)}
                aria-label={t.partner.priceRupeesLabel}
                className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
              />
              <input
                type="number"
                min={5}
                value={svcDuration}
                onChange={(e) => setSvcDuration(e.target.value)}
                aria-label={t.partner.durationMinLabel}
                className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
              />
              <button
                type="submit"
                disabled={submitting}
                className="min-h-[44px] rounded bg-[#1C1B19] px-3 text-xs font-semibold text-white"
              >
                {t.partner.addServiceBtn}
              </button>
            </form>
          </div>

          <div className="border-t border-[#E2DACD] pt-5">
            <h3 className="mb-3 text-base font-semibold text-[#1C1B19]">{t.partner.staffHeading}</h3>
            <div className="space-y-2">
              {setup.staff.map((st) => (
                <div
                  key={st.id}
                  className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-4 py-2.5 text-xs"
                >
                  <span className="font-semibold text-[#1C1B19]">{st.display_name}</span> ·{" "}
                  <span className="text-[#524E48]">
                    {st.shifts.length} {t.partner.shiftsCountLabel} ·{" "}
                    {st.qualified_branch_service_ids.length} {t.partner.servicesCountLabel}
                  </span>
                </div>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!staffName.trim()) {
                  return;
                }
                void runMutation(async () => {
                  const shifts = [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({
                    weekday,
                    start_time: shiftStart,
                    end_time: shiftEnd,
                    timezone: "Asia/Kolkata",
                  }));
                  await createPartnerStaff(
                    session,
                    setup.branch.id,
                    {
                      display_name: staffName.trim(),
                      bio: staffBio.trim() || null,
                      qualified_branch_service_ids: staffServiceIds,
                      shifts,
                    },
                    onSessionUpdate
                  );
                  setStaffName("");
                  setStaffBio("");
                }, t.partner.savedNotice);
              }}
              className="mt-3 space-y-3 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3"
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
                <input
                  type="text"
                  required
                  value={staffName}
                  onChange={(e) => setStaffName(e.target.value)}
                  placeholder={t.partner.staffNameLabel}
                  aria-label={t.partner.staffNameLabel}
                  className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                />
                <input
                  type="text"
                  value={staffBio}
                  onChange={(e) => setStaffBio(e.target.value)}
                  placeholder={t.partner.staffBioLabel}
                  aria-label={t.partner.staffBioLabel}
                  className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                />
                <input
                  type="time"
                  value={shiftStart}
                  onChange={(e) => setShiftStart(e.target.value)}
                  aria-label={`${t.partner.shiftWindowLabel} open`}
                  className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                />
                <input
                  type="time"
                  value={shiftEnd}
                  onChange={(e) => setShiftEnd(e.target.value)}
                  aria-label={`${t.partner.shiftWindowLabel} close`}
                  className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                />
                <button
                  type="submit"
                  disabled={submitting}
                  className="min-h-[44px] rounded bg-[#1C1B19] px-3 text-xs font-semibold text-white"
                >
                  {t.partner.addStaffBtn}
                </button>
              </div>
              {setup.branch_services.length > 0 ? (
                <div className="flex flex-wrap items-center gap-3 text-xs text-[#1C1B19]">
                  <span className="font-medium text-[#524E48]">
                    {t.partner.selectServicesLabel}:
                  </span>
                  {setup.branch_services.map((bs) => {
                    const checked = staffServiceIds.includes(bs.id);
                    return (
                      <label key={bs.id} className="inline-flex min-h-[44px] items-center gap-1.5">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) =>
                            setStaffServiceIds((prev) =>
                              e.target.checked ? [...prev, bs.id] : prev.filter((id) => id !== bs.id)
                            )
                          }
                          className="h-4 w-4 accent-[#4A5D4E]"
                        />
                        {locale === "hi" ? bs.display_name_hi : bs.display_name_en}
                      </label>
                    );
                  })}
                </div>
              ) : null}
            </form>
          </div>

          <div className="border-t border-[#E2DACD] pt-5 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div>
              <h3 className="mb-3 text-base font-semibold text-[#1C1B19]">{t.partner.blocksHeading}</h3>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!blockStartLocal || !blockEndLocal) {
                    return;
                  }
                  void runMutation(async () => {
                    await createPartnerScheduleBlock(
                      session,
                      setup.branch.id,
                      {
                        staff_id: blockStaffId || null,
                        block_type: blockType,
                        start_at: new Date(blockStartLocal).toISOString(),
                        end_at: new Date(blockEndLocal).toISOString(),
                        reason: blockReason.trim() || null,
                      },
                      onSessionUpdate
                    );
                    setBlockReason("");
                  }, t.partner.savedNotice);
                }}
                className="space-y-2 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3"
              >
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={blockType}
                    onChange={(e) => setBlockType(e.target.value as ScheduleBlockType)}
                    aria-label={t.partner.blockTypeLabel}
                    className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                  >
                    <option value="BREAK">BREAK</option>
                    <option value="LEAVE">LEAVE</option>
                    <option value="HOLIDAY">HOLIDAY</option>
                    <option value="MAINTENANCE">MAINTENANCE</option>
                  </select>
                  <select
                    value={blockStaffId}
                    onChange={(e) => setBlockStaffId(e.target.value)}
                    aria-label={t.partner.staffNameLabel}
                    className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                  >
                    <option value="">{t.partner.branchWideLabel}</option>
                    {setup.staff.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.display_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="datetime-local"
                    required
                    value={blockStartLocal}
                    onChange={(e) => setBlockStartLocal(e.target.value)}
                    aria-label={t.partner.blockStartLabel}
                    className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                  />
                  <input
                    type="datetime-local"
                    required
                    value={blockEndLocal}
                    onChange={(e) => setBlockEndLocal(e.target.value)}
                    aria-label={t.partner.blockEndLabel}
                    className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={blockReason}
                    onChange={(e) => setBlockReason(e.target.value)}
                    placeholder={t.partner.blockReasonLabel}
                    aria-label={t.partner.blockReasonLabel}
                    className="min-h-[44px] flex-1 rounded border border-[#E2DACD] bg-white px-2 text-xs"
                  />
                  <button
                    type="submit"
                    disabled={submitting}
                    className="min-h-[44px] rounded bg-[#1C1B19] px-3 text-xs font-semibold text-white"
                  >
                    {t.partner.addBlockBtn}
                  </button>
                </div>
              </form>
              <div className="mt-2 space-y-1.5">
                {setup.schedule_blocks.map((bl) => (
                  <div
                    key={bl.id}
                    className="flex items-center justify-between gap-2 rounded border border-[#E2DACD] bg-[#FAF7F2] px-3 py-2 text-xs"
                  >
                    <span>
                      {bl.block_type} · {formatIstDateTime(bl.start_at, locale)}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        void runMutation(async () => {
                          await deletePartnerScheduleBlock(
                            session,
                            setup.branch.id,
                            bl.id,
                            onSessionUpdate
                          );
                        })
                      }
                      aria-label={t.partner.removeBlockBtn}
                      className="min-h-[44px] px-2 text-[#9E3B33]"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h3 className="mb-3 text-base font-semibold text-[#1C1B19]">{t.partner.chairsHeading}</h3>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!chairName.trim()) {
                    return;
                  }
                  void runMutation(async () => {
                    await createPartnerResource(
                      session,
                      setup.branch.id,
                      { name: chairName.trim(), resource_type: chairType },
                      onSessionUpdate
                    );
                    setChairName("");
                  }, t.partner.savedNotice);
                }}
                className="flex flex-wrap gap-2 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3"
              >
                <input
                  type="text"
                  required
                  value={chairName}
                  onChange={(e) => setChairName(e.target.value)}
                  placeholder={t.partner.chairNameLabel}
                  aria-label={t.partner.chairNameLabel}
                  className="min-h-[44px] flex-1 rounded border border-[#E2DACD] bg-white px-2 text-xs"
                />
                <select
                  value={chairType}
                  onChange={(e) => setChairType(e.target.value as ResourceType)}
                  aria-label={t.partner.chairsHeading}
                  className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-2 text-xs"
                >
                  <option value="BARBER_CHAIR">BARBER_CHAIR</option>
                  <option value="WASH_STATION">WASH_STATION</option>
                  <option value="VIP_ROOM">VIP_ROOM</option>
                </select>
                <button
                  type="submit"
                  disabled={submitting}
                  className="min-h-[44px] rounded bg-[#1C1B19] px-3 text-xs font-semibold text-white"
                >
                  {t.partner.addChairBtn}
                </button>
              </form>
              <div className="mt-2 space-y-1.5">
                {setup.resources.map((res) => (
                  <div
                    key={res.id}
                    className="rounded border border-[#E2DACD] bg-[#FAF7F2] px-3 py-2 text-xs"
                  >
                    <span className="font-semibold text-[#1C1B19]">{res.name}</span> ·{" "}
                    <span className="text-[#524E48]">{res.resource_type}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "kyc" ? (
        <section className="space-y-6 rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
          {selectedBranchSummary && setup ? (
            <div>
              <h3 className="mb-3 flex items-center gap-2 text-base font-semibold text-[#1C1B19]">
                <FileCheck2 className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
                {t.partner.kycHeading}
              </h3>

              {setup.latest_inspection ? (
                <div className="mb-4 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-3 text-xs">
                  <span className="font-semibold text-[#1C1B19]">
                    {t.partner.latestInspectionLabel}:
                  </span>{" "}
                  <span>
                    {setup.latest_inspection.overall_outcome} ({t.admin.scoreShortLabel}{" "}
                    {setup.latest_inspection.numerical_score}/100)
                  </span>
                </div>
              ) : null}

              <form
                onSubmit={(e) => void handleUploadDocument(e)}
                className="flex flex-wrap items-center gap-3 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4"
              >
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value as DocumentType)}
                  aria-label={t.partner.documentTypeLabel}
                  className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs text-[#1C1B19]"
                >
                  <option value="OWNER_ID">OWNER_ID</option>
                  <option value="BUSINESS_REGISTRATION">BUSINESS_REGISTRATION</option>
                  <option value="SHOP_ESTABLISHMENT_LICENSE">SHOP_ESTABLISHMENT_LICENSE</option>
                  <option value="MUNICIPAL_TRADE_LICENSE">MUNICIPAL_TRADE_LICENSE</option>
                  <option value="ADDRESS_PROOF">ADDRESS_PROOF</option>
                  <option value="BANK_PROOF">BANK_PROOF</option>
                </select>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,application/pdf"
                  aria-label={t.partner.chooseFileLabel}
                  onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                  className="min-h-[44px] text-xs text-[#524E48]"
                />
                <button
                  type="submit"
                  disabled={submitting || !selectedFile}
                  className="min-h-[44px] rounded-md bg-[#4A5D4E] px-4 text-xs font-semibold text-white disabled:opacity-50"
                >
                  {t.partner.uploadDocumentBtn}
                </button>
              </form>

              <div className="mt-3 space-y-2">
                {setup.documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-4 py-2.5 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-[#1C1B19]">{doc.document_type}</span> ·{" "}
                      <span className="rounded bg-[#E7ECE8] px-2 py-0.5 font-medium text-[#1C1B19]">
                        {doc.review_status}
                      </span>
                      {doc.rejection_reason ? (
                        <span className="ml-2 text-[#9E3B33]">{doc.rejection_reason}</span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => void openSignedPreview(doc.signed_url)}
                      className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 font-semibold text-[#1C1B19]"
                    >
                      {t.partner.openSignedDocBtn}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="border-t border-[#E2DACD] pt-5">
            <PartnerOnboardingCard
              t={t}
              session={session}
              onSessionUpdate={onSessionUpdate}
              onOnboarded={async (newBranchId) => {
                setSelectedBranchId(newBranchId);
                await loadSelectedBranchData(newBranchId);
                await onRefreshContext();
                setActionNotice(t.partner.savedNotice);
              }}
            />
          </div>
        </section>
      ) : null}

      {(activeTab === "desk" || activeTab === "setup") && !selectedBranchSummary ? (
        <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6 text-sm text-[#524E48]">
          {t.partner.emptyBranches}
        </section>
      ) : null}

      <SignedAssetDialog
        t={t}
        asset={previewAsset}
        onClose={() => {
          if (previewAsset) {
            URL.revokeObjectURL(previewAsset.blobUrl);
          }
          setPreviewAsset(null);
        }}
      />
    </div>
  );
}
