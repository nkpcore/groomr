import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getTranslations,
  type SupportedLocale,
  type TranslationCatalog,
  type UserProfileDto,
} from "@chair/shared-types";
import {
  fetchMobileProfile,
  logoutMobileSession,
  MobileApiError,
} from "@/services/authApi";
import {
  clearMobileSession,
  loadMobileSession,
  type StoredMobileSession,
} from "@/services/tokenStorage";

interface MobileAppContextValue {
  locale: SupportedLocale;
  setLocale: (next: SupportedLocale) => void;
  t: TranslationCatalog;
  session: StoredMobileSession | null;
  setSession: (next: StoredMobileSession | null) => void;
  profile: UserProfileDto | null;
  setProfile: React.Dispatch<React.SetStateAction<UserProfileDto | null>>;
  sessionHydrating: boolean;
  hydrationError: "offline" | "error" | null;
  retryHydration: () => Promise<void>;
  handleSignOut: () => Promise<void>;
}

const MobileAppContext = createContext<MobileAppContextValue | null>(null);

export function MobileAppProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<SupportedLocale>("en");
  const [session, setSession] = useState<StoredMobileSession | null>(null);
  const [profile, setProfile] = useState<UserProfileDto | null>(null);
  const [sessionHydrating, setSessionHydrating] = useState(true);
  const [hydrationError, setHydrationError] = useState<"offline" | "error" | null>(null);

  const hydrate = useCallback(async () => {
    setSessionHydrating(true);
    setHydrationError(null);
    try {
      const stored = await loadMobileSession();
      if (!stored) {
        setSession(null);
        setProfile(null);
        return;
      }
      setSession(stored);
      setLocale(stored.preferredLocale);
      const me = await fetchMobileProfile(stored, (next) => {
        setSession(next);
        if (!next) {
          setProfile(null);
        }
      });
      setProfile(me);
      setLocale(me.preferred_locale);
    } catch (err) {
      if (err instanceof MobileApiError && (err.status === 401 || err.status === 403)) {
        await clearMobileSession();
        setSession(null);
        setProfile(null);
      } else if (err instanceof MobileApiError && err.code === "OFFLINE") {
        setHydrationError("offline");
      } else {
        setHydrationError("error");
      }
    } finally {
      setSessionHydrating(false);
    }
  }, []);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  const handleSignOut = useCallback(async () => {
    if (!session) {
      return;
    }
    try {
      await logoutMobileSession(session);
    } catch {
      // Clear local UI state cleanly even if network/token revoke fails.
    } finally {
      setSession(null);
      setProfile(null);
      setHydrationError(null);
    }
  }, [session]);

  const t = useMemo(() => getTranslations(locale), [locale]);

  const value = useMemo<MobileAppContextValue>(
    () => ({
      locale,
      setLocale,
      t,
      session,
      setSession,
      profile,
      setProfile,
      sessionHydrating,
      hydrationError,
      retryHydration: hydrate,
      handleSignOut,
    }),
    [locale, t, session, profile, sessionHydrating, hydrationError, hydrate, handleSignOut]
  );

  return <MobileAppContext.Provider value={value}>{children}</MobileAppContext.Provider>;
}

export function useMobileApp(): MobileAppContextValue {
  const ctx = useContext(MobileAppContext);
  if (!ctx) {
    throw new Error("useMobileApp must be used inside MobileAppProvider");
  }
  return ctx;
}
