"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { SignedAssetDialog } from "@/components/SignedAssetDialog";
import type {
  AdminVerificationBranchDto,
  AdminVerificationsResponseDto,
  AuditLogListResponseDto,
  TranslationCatalog,
} from "@chair/shared-types";
import {
  ApiClientError,
  fetchSignedPrivateAsset,
  recordAdminInspection,
  reviewAdminDocument,
  updateAdminBranchGovernance,
  type StoredWebSession,
} from "@/lib/api";

interface AdminGovernanceWorkspaceProps {
  t: TranslationCatalog;
  session: StoredWebSession;
  auditData: AuditLogListResponseDto | null;
  verificationsData: AdminVerificationsResponseDto | null;
  onSessionUpdate: (next: StoredWebSession | null) => void;
  onRefreshAll: () => Promise<void>;
}

export function AdminGovernanceWorkspace({
  t,
  session,
  auditData,
  verificationsData,
  onSessionUpdate,
  onRefreshAll,
}: AdminGovernanceWorkspaceProps) {
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>({});
  const [featureLabels, setFeatureLabels] = useState<Record<string, string>>({});
  const [inspectionForms, setInspectionForms] = useState<
    Record<
      string,
      {
        score: string;
        blades: boolean;
        sharps: boolean;
        disinfection: boolean;
        towels: boolean;
        notes: string;
      }
    >
  >({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [previewAsset, setPreviewAsset] = useState<{ blobUrl: string; mimeType: string } | null>(
    null
  );

  useEffect(() => {
    return () => {
      if (previewAsset) {
        URL.revokeObjectURL(previewAsset.blobUrl);
      }
    };
  }, [previewAsset]);

  function getInspForm(branch: AdminVerificationBranchDto) {
    return (
      inspectionForms[branch.branch_id] ?? {
        score: "92",
        blades: branch.latest_inspection?.single_use_blades_ok ?? true,
        sharps: branch.latest_inspection?.sharps_disposal_ok ?? true,
        disinfection: branch.latest_inspection?.instrument_disinfection_ok ?? true,
        towels: branch.latest_inspection?.fresh_towels_ok ?? true,
        notes: "",
      }
    );
  }

  function updateInspForm(
    branch: AdminVerificationBranchDto,
    patch: Partial<{
      score: string;
      blades: boolean;
      sharps: boolean;
      disinfection: boolean;
      towels: boolean;
      notes: string;
    }>
  ) {
    const current = getInspForm(branch);
    setInspectionForms((prev) => ({
      ...prev,
      [branch.branch_id]: { ...current, ...patch },
    }));
  }

  async function runAdminAction(key: string, fn: () => Promise<void>) {
    setBusyId(key);
    setErrorBanner(null);
    try {
      await fn();
      await onRefreshAll();
    } catch (err) {
      setErrorBanner(err instanceof ApiClientError ? err.message : t.states.error);
    } finally {
      setBusyId(null);
    }
  }

  async function inspectSignedDoc(signedUrl: string) {
    setErrorBanner(null);
    try {
      if (previewAsset) {
        URL.revokeObjectURL(previewAsset.blobUrl);
      }
      const res = await fetchSignedPrivateAsset(session, signedUrl, onSessionUpdate);
      setPreviewAsset(res);
    } catch {
      setErrorBanner(t.partner.signedDownloadError);
    }
  }

  return (
    <div className="space-y-6">
      {errorBanner ? (
        <div role="alert" className="rounded-md border border-[#9E3B33]/35 bg-[#F9ECEA] p-3 text-sm text-[#1C1B19]">
          {errorBanner}
        </div>
      ) : null}

      <section className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <ClipboardCheck className="h-5 w-5 text-[#4A5D4E]" aria-hidden="true" />
            <h2
              className="text-lg font-medium text-[#1C1B19]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t.admin.verificationsHeading}
            </h2>
          </div>
          <button
            type="button"
            onClick={() => void onRefreshAll()}
            className="min-h-[44px] rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-3.5 text-xs font-semibold text-[#1C1B19] hover:border-[#4A5D4E]"
          >
            {t.admin.refreshVerifications}
          </button>
        </div>

        {verificationsData ? (
          <p className="mt-3 rounded-md border border-[#4A5D4E]/30 bg-[#E7ECE8] px-3 py-2 text-xs text-[#1C1B19]">
            <strong className="font-semibold">{t.admin.disclaimerPrefix}:</strong>{" "}
            {verificationsData.verification_disclaimer}
          </p>
        ) : null}

        {!verificationsData || verificationsData.items.length === 0 ? (
          <p className="mt-4 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 text-sm text-[#524E48]">
            {t.admin.emptyVerifications}
          </p>
        ) : (
          <div className="mt-4 space-y-5">
            {verificationsData.items.map((item) => {
              const insp = getInspForm(item);
              const featureInput =
                featureLabels[item.branch_id] ?? item.featured_disclosure_label ?? "";
              return (
                <article
                  key={item.branch_id}
                  className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 space-y-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-base font-semibold text-[#1C1B19]">
                        {item.salon_brand_name} — {item.branch_name}
                      </h3>
                      <p className="text-xs text-[#524E48]">
                        {item.city}, {item.state} · {t.admin.statusLabel}: {item.branch_status} ·{" "}
                        {t.admin.badgeLabel}: {item.verification_status}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={busyId === `act:${item.branch_id}`}
                        onClick={() =>
                          void runAdminAction(`act:${item.branch_id}`, async () => {
                            await updateAdminBranchGovernance(
                              session,
                              item.branch_id,
                              { status: "ACTIVE" },
                              onSessionUpdate
                            );
                          })
                        }
                        className="min-h-[44px] rounded border border-[#4A5D4E]/40 bg-[#E7ECE8] px-3 text-xs font-semibold text-[#1C1B19]"
                      >
                        {t.admin.activateBranchBtn}
                      </button>
                      <button
                        type="button"
                        disabled={busyId === `susp:${item.branch_id}`}
                        onClick={() =>
                          void runAdminAction(`susp:${item.branch_id}`, async () => {
                            await updateAdminBranchGovernance(
                              session,
                              item.branch_id,
                              { status: "SUSPENDED", verification_status: "SUSPENDED" },
                              onSessionUpdate
                            );
                          })
                        }
                        className="min-h-[44px] rounded border border-[#9E3B33]/40 bg-[#F9ECEA] px-3 text-xs font-semibold text-[#9E3B33]"
                      >
                        {t.admin.suspendBranchBtn}
                      </button>
                    </div>
                  </div>

                  <div className="border-t border-[#E2DACD] pt-3">
                    <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[#1C1B19]">
                      <FileSearch className="h-3.5 w-3.5 text-[#4A5D4E]" aria-hidden="true" />
                      {t.admin.documentsHeading}
                    </h4>
                    {item.documents.length === 0 ? (
                      <p className="text-xs text-[#524E48]">{t.admin.emptyDocs}</p>
                    ) : (
                      <div className="space-y-2">
                        {item.documents.map((doc) => (
                          <div
                            key={doc.id}
                            className="flex flex-wrap items-center justify-between gap-2 rounded border border-[#E2DACD] bg-white p-2.5 text-xs"
                          >
                            <div>
                              <span className="font-semibold text-[#1C1B19]">
                                {doc.document_type}
                              </span>{" "}
                              <span className="ml-1 rounded bg-[#E7ECE8] px-2 py-0.5 font-medium text-[#1C1B19]">
                                {doc.review_status}
                              </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void inspectSignedDoc(doc.signed_url)}
                                className="min-h-[44px] rounded border border-[#E2DACD] bg-[#FAF7F2] px-2.5 font-semibold text-[#1C1B19]"
                              >
                                {t.admin.previewDocBtn}
                              </button>
                              <button
                                type="button"
                                disabled={busyId === `doc:${doc.id}`}
                                onClick={() =>
                                  void runAdminAction(`doc:${doc.id}`, async () => {
                                    await reviewAdminDocument(
                                      session,
                                      doc.id,
                                      { review_status: "APPROVED" },
                                      onSessionUpdate
                                    );
                                  })
                                }
                                className="min-h-[44px] rounded bg-[#4A5D4E] px-2.5 font-semibold text-white"
                              >
                                {t.admin.approveDocBtn}
                              </button>
                              <input
                                type="text"
                                value={rejectReasons[doc.id] ?? ""}
                                onChange={(e) =>
                                  setRejectReasons((prev) => ({
                                    ...prev,
                                    [doc.id]: e.target.value,
                                  }))
                                }
                                placeholder={t.admin.rejectReasonPlaceholder}
                                aria-label={t.admin.rejectReasonPlaceholder}
                                className="min-h-[44px] w-44 rounded border border-[#E2DACD] px-2 text-xs"
                              />
                              <button
                                type="button"
                                disabled={busyId === `doc:${doc.id}`}
                                onClick={() => {
                                  const reason = (rejectReasons[doc.id] ?? "").trim();
                                  if (!reason) {
                                    setErrorBanner(t.admin.rejectReasonRequired);
                                    return;
                                  }
                                  void runAdminAction(`doc:${doc.id}`, async () => {
                                    await reviewAdminDocument(
                                      session,
                                      doc.id,
                                      { review_status: "REJECTED", rejection_reason: reason },
                                      onSessionUpdate
                                    );
                                  });
                                }}
                                className="min-h-[44px] rounded border border-[#9E3B33]/40 bg-[#F9ECEA] px-2.5 font-semibold text-[#9E3B33]"
                              >
                                {t.admin.rejectDocBtn}
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="border-t border-[#E2DACD] pt-3">
                    <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[#1C1B19]">
                      <AlertTriangle className="h-3.5 w-3.5 text-[#9C744F]" aria-hidden="true" />
                      {t.admin.hygieneHeading}
                    </h4>
                    <p className="mb-2 text-xs text-[#524E48]">{t.admin.criticalOverrideNotice}</p>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        void runAdminAction(`insp:${item.branch_id}`, async () => {
                          await recordAdminInspection(
                            session,
                            item.branch_id,
                            {
                              numerical_score: Math.min(
                                100,
                                Math.max(0, Number.parseInt(insp.score || "0", 10))
                              ),
                              single_use_blades_ok: insp.blades,
                              sharps_disposal_ok: insp.sharps,
                              instrument_disinfection_ok: insp.disinfection,
                              fresh_towels_ok: insp.towels,
                              corrective_action_notes: insp.notes.trim() || null,
                            },
                            onSessionUpdate
                          );
                        });
                      }}
                      className="space-y-3 rounded border border-[#E2DACD] bg-white p-3 text-xs"
                    >
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        <label className="flex min-h-[44px] items-center gap-2 text-[#1C1B19]">
                          <input
                            type="checkbox"
                            checked={insp.blades}
                            onChange={(e) => updateInspForm(item, { blades: e.target.checked })}
                            className="h-4 w-4 accent-[#4A5D4E]"
                          />
                          {t.admin.criticalBladesLabel}
                        </label>
                        <label className="flex min-h-[44px] items-center gap-2 text-[#1C1B19]">
                          <input
                            type="checkbox"
                            checked={insp.sharps}
                            onChange={(e) => updateInspForm(item, { sharps: e.target.checked })}
                            className="h-4 w-4 accent-[#4A5D4E]"
                          />
                          {t.admin.criticalSharpsLabel}
                        </label>
                        <label className="flex min-h-[44px] items-center gap-2 text-[#1C1B19]">
                          <input
                            type="checkbox"
                            checked={insp.disinfection}
                            onChange={(e) =>
                              updateInspForm(item, { disinfection: e.target.checked })
                            }
                            className="h-4 w-4 accent-[#4A5D4E]"
                          />
                          {t.admin.criticalDisinfectionLabel}
                        </label>
                        <label className="flex min-h-[44px] items-center gap-2 text-[#1C1B19]">
                          <input
                            type="checkbox"
                            checked={insp.towels}
                            onChange={(e) => updateInspForm(item, { towels: e.target.checked })}
                            className="h-4 w-4 accent-[#4A5D4E]"
                          />
                          {t.admin.criticalTowelsLabel}
                        </label>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="text-xs font-medium text-[#1C1B19]">
                          {t.admin.scoreLabel}
                          <input
                            type="number"
                            min={0}
                            max={100}
                            value={insp.score}
                            onChange={(e) => updateInspForm(item, { score: e.target.value })}
                            className="ml-2 min-h-[44px] w-20 rounded border border-[#E2DACD] px-2"
                          />
                        </label>
                        <input
                          type="text"
                          value={insp.notes}
                          onChange={(e) => updateInspForm(item, { notes: e.target.value })}
                          placeholder={t.admin.correctiveNotesLabel}
                          aria-label={t.admin.correctiveNotesLabel}
                          className="min-h-[44px] flex-1 rounded border border-[#E2DACD] px-2"
                        />
                        <button
                          type="submit"
                          disabled={busyId === `insp:${item.branch_id}`}
                          className="min-h-[44px] rounded bg-[#1C1B19] px-3 font-semibold text-white"
                        >
                          {t.admin.submitInspectionBtn}
                        </button>
                      </div>
                      {item.latest_inspection ? (
                        <p className="inline-flex items-center gap-1.5 text-xs text-[#524E48]">
                          <CheckCircle2 className="h-3.5 w-3.5 text-[#4A5D4E]" aria-hidden="true" />
                          {item.latest_inspection.overall_outcome} · {t.admin.scoreShortLabel}{" "}
                          {item.latest_inspection.numerical_score}/100
                        </p>
                      ) : null}
                    </form>
                  </div>

                  <div className="border-t border-[#E2DACD] pt-3 flex flex-wrap items-center gap-2 text-xs">
                    <Sparkles className="h-3.5 w-3.5 text-[#9C744F]" aria-hidden="true" />
                    <span className="font-semibold text-[#1C1B19]">
                      {t.admin.governanceHeading}:
                    </span>
                    <input
                      type="text"
                      value={featureInput}
                      onChange={(e) =>
                        setFeatureLabels((prev) => ({ ...prev, [item.branch_id]: e.target.value }))
                      }
                      placeholder={t.admin.featureLabelPlaceholder}
                      aria-label={t.admin.featureLabelPlaceholder}
                      className="min-h-[44px] w-52 rounded border border-[#E2DACD] bg-white px-2"
                    />
                    <button
                      type="button"
                      disabled={busyId === `feat:${item.branch_id}`}
                      onClick={() => {
                        if (!featureInput.trim()) {
                          setErrorBanner(t.admin.featuredLabelRequired);
                          return;
                        }
                        void runAdminAction(`feat:${item.branch_id}`, async () => {
                          await updateAdminBranchGovernance(
                            session,
                            item.branch_id,
                            {
                              is_featured: true,
                              featured_disclosure_label: featureInput.trim(),
                            },
                            onSessionUpdate
                          );
                        });
                      }}
                      className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 font-semibold text-[#1C1B19] disabled:opacity-50"
                    >
                      {t.admin.enableFeaturedBtn}
                    </button>
                    {item.is_featured ? (
                      <button
                        type="button"
                        disabled={busyId === `unfeat:${item.branch_id}`}
                        onClick={() =>
                          void runAdminAction(`unfeat:${item.branch_id}`, async () => {
                            await updateAdminBranchGovernance(
                              session,
                              item.branch_id,
                              { is_featured: false, featured_disclosure_label: null },
                              onSessionUpdate
                            );
                          })
                        }
                        className="min-h-[44px] rounded border border-[#E2DACD] bg-[#FAF7F2] px-3 font-semibold text-[#524E48] disabled:opacity-50"
                      >
                        {t.admin.disableFeaturedBtn}
                      </button>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

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
            onClick={() => void onRefreshAll()}
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
