"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { AlertCircle, CheckCircle2, Smartphone } from "lucide-react";
import {
  isValidOtpCode,
  normalizePhoneE164,
  type AuthTokenResponse,
  type OTPRequestResponse,
  type TranslationCatalog,
} from "@chair/shared-types";
import { ApiClientError, requestOtp, verifyOtp } from "@/lib/api";

interface OtpAuthCardProps {
  t: TranslationCatalog;
  onAuthenticated: (tokens: AuthTokenResponse) => void;
}

export function OtpAuthCard({ t, onAuthenticated }: OtpAuthCardProps) {
  const headingId = useId();
  const phoneInputRef = useRef<HTMLInputElement>(null);
  const otpFormRef = useRef<HTMLFormElement>(null);
  const otpInputRef = useRef<HTMLInputElement>(null);
  const otpAbortRef = useRef<AbortController | null>(null);

  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [phoneRaw, setPhoneRaw] = useState("");
  const [phoneInteracted, setPhoneInteracted] = useState(false);
  const [phoneClientError, setPhoneClientError] = useState<string | null>(null);

  const [otpRaw, setOtpRaw] = useState("");
  const [otpInteracted, setOtpInteracted] = useState(false);
  const [otpClientError, setOtpClientError] = useState<string | null>(null);

  const [challenge, setChallenge] = useState<OTPRequestResponse | null>(null);
  const [normalizedPhone, setNormalizedPhone] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  function stopWebOtpListener() {
    if (otpAbortRef.current) {
      otpAbortRef.current.abort();
      otpAbortRef.current = null;
    }
  }

  async function verifyCodeDirect(codeRaw: string) {
    stopWebOtpListener();
    setOtpInteracted(true);
    setServerError(null);

    const trimmedCode = codeRaw.trim();
    const errMsg = validateOtpField(trimmedCode);
    if (errMsg || !challenge || !normalizedPhone) {
      setOtpClientError(errMsg ?? t.auth.otpError);
      otpInputRef.current?.focus();
      return;
    }

    setOtpClientError(null);
    setSubmitting(true);
    try {
      const tokens = await verifyOtp({
        challenge_id: challenge.challenge_id,
        phone_e164: normalizedPhone,
        otp_code: trimmedCode,
      });
      onAuthenticated(tokens);
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.code === "OFFLINE") {
          setServerError(t.states.offline);
        } else if (err.code === "NETWORK_ERROR") {
          setServerError(t.states.networkError);
        } else {
          setServerError(err.message);
        }
      } else {
        setServerError(t.states.error);
      }
      otpInputRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    if (step !== "otp" || typeof window === "undefined" || !("OTPCredential" in window)) {
      return () => stopWebOtpListener();
    }

    stopWebOtpListener();
    const ac = new AbortController();
    otpAbortRef.current = ac;

    type OtpCredentialResult = { code?: string } | null;
    const credentialsApi = navigator.credentials as unknown as {
      get: (options: Record<string, unknown>) => Promise<OtpCredentialResult>;
    };

    void credentialsApi
      .get({
        otp: { transport: ["sms"] },
        signal: ac.signal,
      })
      .then((otpCred) => {
        if (otpCred?.code && isValidOtpCode(otpCred.code)) {
          setOtpRaw(otpCred.code);
          setOtpClientError(null);
          void verifyCodeDirect(otpCred.code);
        }
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
      });

    return () => stopWebOtpListener();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, challenge?.challenge_id]);

  function validatePhoneField(raw: string): string | null {
    return normalizePhoneE164(raw) ? null : t.auth.phoneError;
  }

  function validateOtpField(raw: string): string | null {
    return isValidOtpCode(raw) ? null : t.auth.otpError;
  }

  async function submitPhoneRequest(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setPhoneInteracted(true);
    setServerError(null);

    const parsedPhone = normalizePhoneE164(phoneRaw);
    if (!parsedPhone) {
      setPhoneClientError(t.auth.phoneError);
      phoneInputRef.current?.focus();
      return;
    }

    setPhoneClientError(null);
    setSubmitting(true);
    try {
      const challengeRes = await requestOtp({ phone_e164: parsedPhone });
      setNormalizedPhone(parsedPhone);
      setChallenge(challengeRes);
      setOtpRaw("");
      setOtpInteracted(false);
      setOtpClientError(null);
      setStep("otp");
      requestAnimationFrame(() => otpInputRef.current?.focus());
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.code === "OFFLINE") {
          setServerError(t.states.offline);
        } else if (err.code === "NETWORK_ERROR") {
          setServerError(t.states.networkError);
        } else {
          setServerError(err.message);
        }
      } else {
        setServerError(t.states.error);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function submitOtpVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await verifyCodeDirect(otpRaw);
  }

  const showPhoneError = Boolean(phoneInteracted && phoneClientError);
  const showOtpError = Boolean(otpInteracted && otpClientError);

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-lg border border-[#E2DACD] bg-[#F4EFE6] p-6"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-[#E7ECE8] p-2 text-[#4A5D4E]">
          <Smartphone className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <h2
            id={headingId}
            className="text-xl font-medium text-[#1C1B19]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {step === "phone" ? t.auth.signInHeading : t.auth.otpHeading}
          </h2>
          <p className="mt-1 text-sm text-[#524E48]">{t.auth.signInSubtitle}</p>
        </div>
      </div>

      {serverError ? (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2.5 rounded-md border border-[#9E3B33]/35 bg-[#F9ECEA] p-3 text-sm text-[#1C1B19]"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#9E3B33]" aria-hidden="true" />
          <span>{serverError}</span>
        </div>
      ) : null}

      {step === "phone" ? (
        <form
          method="POST"
          noValidate
          aria-labelledby={headingId}
          onSubmit={(e) => void submitPhoneRequest(e)}
          className="mt-5 max-w-md space-y-4"
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="chair-phone-input" className="text-sm font-medium text-[#1C1B19]">
              {t.auth.phoneLabel}
            </label>
            <p id="chair-phone-hint" className="text-xs text-[#524E48]">
              {t.auth.phoneHint}
            </p>
            <input
              ref={phoneInputRef}
              id="chair-phone-input"
              name="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              enterKeyHint="next"
              required
              aria-invalid={showPhoneError ? "true" : "false"}
              aria-describedby={
                showPhoneError ? "chair-phone-hint chair-phone-error" : "chair-phone-hint"
              }
              value={phoneRaw}
              onChange={(e) => {
                setPhoneRaw(e.target.value);
                setServerError(null);
                if (phoneInteracted && normalizePhoneE164(e.target.value)) {
                  setPhoneClientError(null);
                }
              }}
              onBlur={() => {
                if (phoneRaw.trim().length > 0) {
                  setPhoneInteracted(true);
                  setPhoneClientError(validatePhoneField(phoneRaw));
                }
              }}
              className="chair-input w-full rounded-md border bg-[#FAF7F2] px-3.5 py-2.5 text-[#1C1B19]"
              placeholder="+919000000003"
            />
            {showPhoneError ? (
              <p id="chair-phone-error" className="flex items-center gap-1.5 text-xs text-[#9E3B33]">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>{phoneClientError}</span>
              </p>
            ) : null}
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="min-h-[48px] rounded-md bg-[#4A5D4E] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#3B4B3F] disabled:opacity-60"
          >
            {submitting ? t.auth.sendingOtp : t.auth.requestOtpButton}
          </button>
        </form>
      ) : (
        <form
          ref={otpFormRef}
          method="POST"
          noValidate
          aria-labelledby={headingId}
          onSubmit={(e) => void submitOtpVerification(e)}
          className="mt-5 max-w-md space-y-4"
        >
          {challenge ? (
            <div className="rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-3.5 py-2.5 text-xs text-[#524E48]">
              <p className="font-medium text-[#1C1B19]">
                {t.auth.otpSentPrefix} {challenge.masked_phone}
              </p>
              {challenge.delivery_mode === "mock" ? (
                <p className="mt-1 flex items-center gap-1.5 text-[#4A5D4E]">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span>{t.auth.mockOtpHint}</span>
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="flex flex-col gap-1.5">
            <label htmlFor="chair-otp-input" className="text-sm font-medium text-[#1C1B19]">
              {t.auth.otpLabel}
            </label>
            <p id="chair-otp-hint" className="text-xs text-[#524E48]">
              {t.auth.otpHint}
            </p>
            <input
              ref={otpInputRef}
              id="chair-otp-input"
              name="otp"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              enterKeyHint="done"
              required
              aria-invalid={showOtpError ? "true" : "false"}
              aria-describedby={showOtpError ? "chair-otp-hint chair-otp-error" : "chair-otp-hint"}
              value={otpRaw}
              onChange={(e) => {
                setOtpRaw(e.target.value);
                setServerError(null);
                if (otpInteracted && isValidOtpCode(e.target.value)) {
                  setOtpClientError(null);
                }
              }}
              onBlur={() => {
                if (otpRaw.trim().length > 0) {
                  setOtpInteracted(true);
                  setOtpClientError(validateOtpField(otpRaw));
                }
              }}
              className="chair-input w-full rounded-md border bg-[#FAF7F2] px-3.5 py-2.5 font-mono text-lg tracking-[0.28em] text-[#1C1B19]"
              placeholder="123456"
            />
            {showOtpError ? (
              <p id="chair-otp-error" className="flex items-center gap-1.5 text-xs text-[#9E3B33]">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>{otpClientError}</span>
              </p>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="min-h-[48px] rounded-md bg-[#4A5D4E] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#3B4B3F] disabled:opacity-60"
            >
              {submitting ? t.auth.verifyingOtp : t.auth.verifyOtpButton}
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={() => void submitPhoneRequest()}
              className="min-h-[44px] rounded-md border border-[#E2DACD] bg-[#FAF7F2] px-4 text-sm font-medium text-[#1C1B19] hover:border-[#4A5D4E] disabled:opacity-60"
            >
              {t.auth.resendOtpButton}
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={() => {
                stopWebOtpListener();
                setStep("phone");
                setServerError(null);
              }}
              className="min-h-[44px] rounded-md px-3 text-sm font-medium text-[#524E48] underline-offset-4 hover:underline"
            >
              {t.auth.changePhoneButton}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
