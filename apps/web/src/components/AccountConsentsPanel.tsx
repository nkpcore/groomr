"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import { AlertCircle, CheckCircle2, FileCheck2 } from "lucide-react";
import {
  ALL_CONSENT_TYPES,
  type ConsentType,
  type SupportedLocale,
  type TranslationCatalog,
  type UserProfileDto,
} from "@chair/shared-types";
import {
  ApiClientError,
  updateMyConsents,
  updateMyProfile,
  type StoredWebSession,
} from "@/lib/api";

interface AccountConsentsPanelProps {
  t: TranslationCatalog;
  session: StoredWebSession;
  profile: UserProfileDto;
  onSessionUpdate: (next: StoredWebSession | null) => void;
  onProfileUpdate: (next: UserProfileDto) => void;
  onLocaleChange: (nextLocale: SupportedLocale) => void;
}

const CONSENT_LABEL_MAP: Record<
  ConsentType,
  {
    labelKey:
      | "consentTermsLabel"
      | "consentPrivacyLabel"
      | "consentLocationLabel"
      | "consentStylePhotosLabel"
      | "consentMarketingLabel";
    descKey:
      | "consentTermsDesc"
      | "consentPrivacyDesc"
      | "consentLocationDesc"
      | "consentStylePhotosDesc"
      | "consentMarketingDesc";
  }
> = {
  TERMS: { labelKey: "consentTermsLabel", descKey: "consentTermsDesc" },
  PRIVACY_DPDP: { labelKey: "consentPrivacyLabel", descKey: "consentPrivacyDesc" },
  LOCATION: { labelKey: "consentLocationLabel", descKey: "consentLocationDesc" },
  STYLE_PASSPORT_PHOTOS: {
    labelKey: "consentStylePhotosLabel",
    descKey: "consentStylePhotosDesc",
  },
  MARKETING: { labelKey: "consentMarketingLabel", descKey: "consentMarketingDesc" },
};

export function AccountConsentsPanel({
  t,
  session,
  profile,
  onSessionUpdate,
  onProfileUpdate,
  onLocaleChange,
}: AccountConsentsPanelProps) {
  const profileHeadingId = useId();
  const consentsHeadingId = useId();

  const [fullName, setFullName] = useState(profile.full_name ?? "");
  const [email, setEmail] = useState(profile.email ?? "");
  const [preferredLocale, setPreferredLocale] = useState<SupportedLocale>(profile.preferred_locale);
  const [emailInteracted, setEmailInteracted] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileNotice, setProfileNotice] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [consentSelections, setConsentSelections] = useState<Record<ConsentType, boolean>>(() => {
    const initial = {} as Record<ConsentType, boolean>;
    for (const ctype of ALL_CONSENT_TYPES) {
      const found = profile.consents.find((c) => c.consent_type === ctype);
      initial[ctype] = Boolean(found?.granted);
    }
    return initial;
  });
  const [savingConsents, setSavingConsents] = useState(false);
  const [consentsNotice, setConsentsNotice] = useState<string | null>(null);
  const [consentsError, setConsentsError] = useState<string | null>(null);

  useEffect(() => {
    setFullName(profile.full_name ?? "");
    setEmail(profile.email ?? "");
    setPreferredLocale(profile.preferred_locale);
  }, [profile.id, profile.full_name, profile.email, profile.preferred_locale]);

  useEffect(() => {
    const synced = {} as Record<ConsentType, boolean>;
    for (const ctype of ALL_CONSENT_TYPES) {
      const found = profile.consents.find((c) => c.consent_type === ctype);
      synced[ctype] = Boolean(found?.granted);
    }
    setConsentSelections(synced);
  }, [profile.id, profile.consents]);

  const emailInvalid =
    emailInteracted && email.trim().length > 0 && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  async function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailInteracted(true);
    setProfileNotice(null);
    setProfileError(null);

    const trimmedEmail = email.trim();
    if (trimmedEmail.length > 0 && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmedEmail)) {
      setProfileError(t.profile.emailError);
      return;
    }

    setSavingProfile(true);
    try {
      const updated = await updateMyProfile(
        session,
        {
          full_name: fullName.trim() || null,
          email: trimmedEmail || null,
          preferred_locale: preferredLocale,
        },
        onSessionUpdate
      );
      onProfileUpdate(updated);
      onLocaleChange(updated.preferred_locale);
      setProfileNotice(t.profile.profileSaved);
    } catch (err) {
      setProfileError(err instanceof ApiClientError ? err.message : t.states.error);
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleConsentsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConsentsNotice(null);
    setConsentsError(null);
    setSavingConsents(true);

    try {
      const response = await updateMyConsents(
        session,
        {
          decisions: ALL_CONSENT_TYPES.map((ctype) => ({
            consent_type: ctype,
            granted: consentSelections[ctype],
            version: "v1.0",
          })),
        },
        onSessionUpdate
      );
      onProfileUpdate({ ...profile, consents: response.consents });
      setConsentsNotice(t.consents.savedNotice);
    } catch (err) {
      setConsentsError(err instanceof ApiClientError ? err.message : t.states.error);
    } finally {
      setSavingConsents(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <section
        aria-labelledby={profileHeadingId}
        className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6"
      >
        <h2
          id={profileHeadingId}
          className="text-lg font-medium text-[#1C1B19]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {t.profile.sectionHeading}
        </h2>

        <form
          method="POST"
          noValidate
          aria-labelledby={profileHeadingId}
          onSubmit={(e) => void handleProfileSubmit(e)}
          className="mt-4 space-y-4"
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="chair-full-name" className="text-sm font-medium text-[#1C1B19]">
              {t.profile.fullNameLabel}
            </label>
            <input
              id="chair-full-name"
              name="full_name"
              type="text"
              autoComplete="name"
              maxLength={120}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="chair-input w-full rounded-md border bg-[#FAF7F2] px-3.5 py-2 text-[#1C1B19]"
              placeholder={t.profile.noNameYet}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="chair-email" className="text-sm font-medium text-[#1C1B19]">
              {t.profile.emailLabel}
            </label>
            <p id="chair-email-hint" className="text-xs text-[#524E48]">
              {t.profile.emailHint}
            </p>
            <input
              id="chair-email"
              name="email"
              type="email"
              autoComplete="email"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={emailInvalid ? "true" : "false"}
              aria-describedby={emailInvalid ? "chair-email-hint chair-email-error" : "chair-email-hint"}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setProfileError(null);
              }}
              onBlur={() => setEmailInteracted(true)}
              className="chair-input w-full rounded-md border bg-[#FAF7F2] px-3.5 py-2 text-[#1C1B19]"
              placeholder="name@example.com"
            />
            {emailInvalid ? (
              <p id="chair-email-error" className="text-xs text-[#9E3B33]">
                {t.profile.emailError}
              </p>
            ) : null}
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-[#1C1B19]">{t.profile.localeLabel}</legend>
            <div className="flex gap-4">
              {(["en", "hi"] as const).map((lang) => (
                <div key={lang} className="flex items-center gap-2">
                  <input
                    id={`chair-profile-lang-${lang}`}
                    type="radio"
                    name="preferred_locale"
                    value={lang}
                    checked={preferredLocale === lang}
                    onChange={() => setPreferredLocale(lang)}
                    className="h-4 w-4 accent-[#4A5D4E]"
                  />
                  <label
                    htmlFor={`chair-profile-lang-${lang}`}
                    className="min-h-[44px] inline-flex items-center text-sm text-[#1C1B19]"
                  >
                    {lang === "en" ? "English (EN)" : "हिन्दी (HI)"}
                  </label>
                </div>
              ))}
            </div>
          </fieldset>

          {profileError ? (
            <p role="alert" className="flex items-center gap-1.5 text-xs text-[#9E3B33]">
              <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{profileError}</span>
            </p>
          ) : null}

          {profileNotice ? (
            <p role="status" className="flex items-center gap-1.5 text-xs font-medium text-[#4A5D4E]">
              <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{profileNotice}</span>
            </p>
          ) : null}

          <button
            type="submit"
            disabled={savingProfile}
            className="min-h-[48px] rounded-md bg-[#1C1B19] px-5 text-sm font-semibold text-white hover:bg-[#2D2B28] disabled:opacity-60"
          >
            {savingProfile ? t.profile.savingProfile : t.profile.saveProfileButton}
          </button>
        </form>
      </section>

      <section
        aria-labelledby={consentsHeadingId}
        className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6"
      >
        <div className="flex items-start gap-2.5">
          <FileCheck2 className="mt-1 h-5 w-5 shrink-0 text-[#4A5D4E]" aria-hidden="true" />
          <div>
            <h2
              id={consentsHeadingId}
              className="text-lg font-medium text-[#1C1B19]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t.consents.sectionHeading}
            </h2>
            <p className="mt-1 text-xs text-[#524E48]">{t.consents.sectionDescription}</p>
          </div>
        </div>

        <form
          method="POST"
          aria-labelledby={consentsHeadingId}
          onSubmit={(e) => void handleConsentsSubmit(e)}
          className="mt-4 space-y-4"
        >
          <fieldset className="space-y-3">
            <legend className="text-sm font-medium text-[#1C1B19]">{t.consents.legend}</legend>
            {ALL_CONSENT_TYPES.map((ctype) => {
              const keys = CONSENT_LABEL_MAP[ctype];
              const existing = profile.consents.find((c) => c.consent_type === ctype);
              const checkboxId = `chair-consent-${ctype.toLowerCase()}`;
              const statusText = existing?.granted
                ? t.consents.grantedLabel
                : existing?.revoked_at
                  ? t.consents.revokedLabel
                  : t.consents.notGrantedLabel;

              return (
                <div
                  key={ctype}
                  className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-3.5 py-2.5"
                >
                  <div className="flex items-start gap-3">
                    <input
                      id={checkboxId}
                      name={ctype}
                      type="checkbox"
                      checked={consentSelections[ctype]}
                      onChange={(e) => {
                        setConsentSelections((prev) => ({
                          ...prev,
                          [ctype]: e.target.checked,
                        }));
                        setConsentsNotice(null);
                      }}
                      className="mt-1 h-5 w-5 shrink-0 accent-[#4A5D4E]"
                    />
                    <div className="flex-1">
                      <label
                        htmlFor={checkboxId}
                        className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-[#1C1B19]"
                      >
                        <span>{t.consents[keys.labelKey]}</span>
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${
                            existing?.granted
                              ? "bg-[#E7ECE8] text-[#1C1B19]"
                              : "bg-[#F4EFE6] text-[#524E48]"
                          }`}
                        >
                          {statusText}
                        </span>
                      </label>
                      <p className="mt-1 text-xs text-[#524E48]">{t.consents[keys.descKey]}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </fieldset>

          {consentsError ? (
            <p role="alert" className="flex items-center gap-1.5 text-xs text-[#9E3B33]">
              <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{consentsError}</span>
            </p>
          ) : null}

          {consentsNotice ? (
            <p role="status" className="flex items-center gap-1.5 text-xs font-medium text-[#4A5D4E]">
              <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{consentsNotice}</span>
            </p>
          ) : null}

          <button
            type="submit"
            disabled={savingConsents}
            className="min-h-[48px] rounded-md bg-[#4A5D4E] px-5 text-sm font-semibold text-white hover:bg-[#3B4B3F] disabled:opacity-60"
          >
            {savingConsents ? t.consents.saving : t.consents.saveButton}
          </button>
        </form>
      </section>
    </div>
  );
}
