"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import type { TranslationCatalog } from "@chair/shared-types";
import { ApiClientError, createPartnerSalon, type StoredWebSession } from "@/lib/api";

interface PartnerOnboardingCardProps {
  t: TranslationCatalog;
  session: StoredWebSession;
  onSessionUpdate: (next: StoredWebSession | null) => void;
  onOnboarded: (branchId: string) => Promise<void>;
}

export function PartnerOnboardingCard({
  t,
  session,
  onSessionUpdate,
  onOnboarded,
}: PartnerOnboardingCardProps) {
  const [legalName, setLegalName] = useState("");
  const [brandName, setBrandName] = useState("");
  const [gstin, setGstin] = useState("");
  const [newBranchName, setNewBranchName] = useState("");
  const [addressLine1, setAddressLine1] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [pincode, setPincode] = useState("");
  const [latInput, setLatInput] = useState("12.9718");
  const [lngInput, setLngInput] = useState("77.6412");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const lat = Number.parseFloat(latInput);
    const lng = Number.parseFloat(lngInput);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setErrorMsg(t.states.error);
      return;
    }

    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await createPartnerSalon(
        session,
        {
          legal_name: legalName.trim(),
          brand_name: brandName.trim(),
          gstin: gstin.trim() || null,
          branch_name: newBranchName.trim(),
          address_line1: addressLine1.trim(),
          city: city.trim(),
          state: stateName.trim(),
          pincode: pincode.trim(),
          lat,
          lng,
          initial_chair_count: 2,
        },
        onSessionUpdate
      );
      setLegalName("");
      setBrandName("");
      setGstin("");
      setNewBranchName("");
      setAddressLine1("");
      setCity("");
      setStateName("");
      setPincode("");
      await onOnboarded(res.branch.id);
    } catch (err) {
      setErrorMsg(err instanceof ApiClientError ? err.message : t.states.error);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h3 className="mb-3 flex items-center gap-2 text-base font-semibold text-[#1C1B19]">
        <ShieldCheck className="h-4 w-4 text-[#4A5D4E]" aria-hidden="true" />
        {t.partner.onboardHeading}
      </h3>
      {errorMsg ? (
        <div role="alert" className="mb-3 rounded border border-[#9E3B33]/35 bg-[#F9ECEA] p-2.5 text-xs text-[#1C1B19]">
          {errorMsg}
        </div>
      ) : null}
      <form
        onSubmit={(e) => void handleSubmit(e)}
        className="grid grid-cols-1 gap-3 rounded-md border border-[#E2DACD] bg-[#FAF7F2] p-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <input
          type="text"
          required
          value={legalName}
          onChange={(e) => setLegalName(e.target.value)}
          placeholder={t.partner.legalNameLabel}
          aria-label={t.partner.legalNameLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          required
          value={brandName}
          onChange={(e) => setBrandName(e.target.value)}
          placeholder={t.partner.brandNameLabel}
          aria-label={t.partner.brandNameLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          value={gstin}
          onChange={(e) => setGstin(e.target.value)}
          placeholder={t.partner.gstinLabel}
          aria-label={t.partner.gstinLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          required
          value={newBranchName}
          onChange={(e) => setNewBranchName(e.target.value)}
          placeholder={t.partner.branchNameLabel}
          aria-label={t.partner.branchNameLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          required
          value={addressLine1}
          onChange={(e) => setAddressLine1(e.target.value)}
          placeholder={t.partner.addressLabel}
          aria-label={t.partner.addressLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          required
          value={city}
          onChange={(e) => setCity(e.target.value)}
          placeholder={t.partner.cityLabel}
          aria-label={t.partner.cityLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          required
          value={stateName}
          onChange={(e) => setStateName(e.target.value)}
          placeholder={t.partner.stateLabel}
          aria-label={t.partner.stateLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <input
          type="text"
          required
          value={pincode}
          onChange={(e) => setPincode(e.target.value)}
          placeholder={t.partner.pincodeLabel}
          aria-label={t.partner.pincodeLabel}
          className="min-h-[44px] rounded border border-[#E2DACD] bg-white px-3 text-xs"
        />
        <div className="flex gap-2">
          <input
            type="number"
            step="any"
            required
            value={latInput}
            onChange={(e) => setLatInput(e.target.value)}
            aria-label={t.partner.latLabel}
            className="min-h-[44px] w-1/2 rounded border border-[#E2DACD] bg-white px-2 text-xs"
          />
          <input
            type="number"
            step="any"
            required
            value={lngInput}
            onChange={(e) => setLngInput(e.target.value)}
            aria-label={t.partner.lngLabel}
            className="min-h-[44px] w-1/2 rounded border border-[#E2DACD] bg-white px-2 text-xs"
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="min-h-[44px] rounded-md bg-[#1C1B19] px-4 text-xs font-semibold text-white sm:col-span-2 lg:col-span-3"
        >
          {t.partner.registerSalonBtn}
        </button>
      </form>
    </div>
  );
}
