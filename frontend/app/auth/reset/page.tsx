"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, CheckCircle2, KeyRound, Loader2 } from "lucide-react";

import { completePasswordReset } from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";

/** Fast path only; the API enforces the deployment's real minimum. */
const MIN_LENGTH = 8;

let cachedToken: string | null | undefined;

/**
 * Read the recovery token from the link Supabase sent.
 *
 * GoTrue redirects with the session in the URL *fragment*
 * (`#access_token=…&type=recovery`), which never reaches a server; a few
 * templates use a query parameter instead, so both are accepted. The fragment
 * is removed from the address bar immediately after reading it, so the token
 * is not left in history or in a screenshot of the URL.
 */
function takeToken(): string | null {
  if (cachedToken !== undefined) return cachedToken;
  const hash = window.location.hash.replace(/^#/, "");
  const fromHash = new URLSearchParams(hash).get("access_token");
  const fromQuery = new URLSearchParams(window.location.search).get("access_token");
  const token = fromHash || fromQuery;
  if (hash || fromQuery) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  // Cached because React re-runs mount effects in development, by which time
  // the fragment has already been stripped.
  cachedToken = token && token.length > 10 ? token : null;
  return cachedToken;
}

function initialLanguage(): Language {
  const stored = window.localStorage.getItem("eais-lang");
  if (stored === "en" || stored === "ar") return stored;
  return window.navigator.language.toLowerCase().startsWith("ar") ? "ar" : "en";
}

export default function ResetPasswordPage() {
  const [language, setLanguage] = useState<Language>("en");
  const [token, setToken] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setLanguage(initialLanguage());
    setToken(takeToken());
    setChecked(true);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
  }, [language]);

  const t = COPY[language];

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) return;
    setError(null);
    if (password !== confirm) {
      setError(t.resetMismatch);
      return;
    }
    if (password.length < MIN_LENGTH) {
      setError(t.resetTooShort.replace("{count}", String(MIN_LENGTH)));
      return;
    }
    setBusy(true);
    try {
      await completePasswordReset(token, password);
      setPassword("");
      setConfirm("");
      setDone(true);
    } catch (cause) {
      setError(friendlyError(cause, language, "reset"));
    } finally {
      setBusy(false);
    }
  };

  if (!checked) return null;

  const field =
    "w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent-500/50";

  return (
    <main className="flex min-h-full items-start justify-center px-4 py-16">
      <section aria-label={t.resetTitle} className="card w-full max-w-md p-6 shadow-glow">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-500/30 bg-accent-500/10">
            <KeyRound className="h-4 w-4 text-accent-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-base font-semibold">{t.resetTitle}</h1>
            <p className="mt-1 text-xs text-slate-400">{t.resetIntro}</p>
          </div>
        </div>

        {!token && !done ? (
          <div className="mt-5">
            <p role="alert" className="flex items-start gap-2 text-xs text-red-300">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t.resetInvalidLink}
            </p>
          </div>
        ) : null}

        {token && !done ? (
          <form onSubmit={submit} className="mt-5 space-y-3">
            <label className="block text-xs text-slate-300">
              {t.resetNewPassword}
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={MIN_LENGTH}
                maxLength={200}
                className={`mt-1 ${field}`}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={busy}
              />
            </label>
            <label className="block text-xs text-slate-300">
              {t.resetConfirm}
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={MIN_LENGTH}
                maxLength={200}
                className={`mt-1 ${field}`}
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                disabled={busy}
              />
            </label>
            {error ? (
              <p role="alert" className="flex items-start gap-2 text-xs text-red-300">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {error}
              </p>
            ) : null}
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t.resetWorking}
                </>
              ) : (
                t.resetSubmit
              )}
            </button>
          </form>
        ) : null}

        {done ? (
          <div role="status" className="mt-5 flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3 text-xs text-emerald-200">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              <strong className="block text-emerald-100">{t.resetDone}</strong>
              {t.resetDoneHint}
            </span>
          </div>
        ) : null}

        <Link
          href="/"
          className="mt-5 inline-flex items-center gap-1.5 text-xs text-slate-300 hover:text-slate-100"
        >
          <ArrowLeft className="h-3.5 w-3.5 rtl:rotate-180" />
          {t.resetBack}
        </Link>
      </section>
    </main>
  );
}
