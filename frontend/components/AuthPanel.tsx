"use client";

import { useState } from "react";
import {
  LogIn,
  LogOut,
  Loader2,
  ShieldCheck,
  UserPlus,
  UserRound,
  X,
  Users,
} from "lucide-react";

import { getMe, login, logout, register, type AuthConfig, type AuthUser } from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";

type Mode = "signin" | "register";

/**
 * Account panel: the current identity, sign-in, registration and sign-out.
 * Registration is public by default; when the deployment sets `INVITE_CODE`
 * the form also asks for the code. The password only ever lives in this
 * component's state for the duration of the request; nothing is written to
 * storage.
 */
export default function AuthPanel({
  language,
  user,
  config,
  onClose,
  onUser,
  onSignedOut,
  onManageUsers,
}: {
  language: Language;
  user: AuthUser | null;
  config: AuthConfig;
  onClose: () => void;
  onUser: (user: AuthUser) => void;
  onSignedOut: () => void;
  onManageUsers: () => void;
}) {
  const copy = COPY[language];
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = user?.role === "admin";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") {
        await login(email.trim(), password);
      } else {
        await register(email.trim(), password, invite.trim(), displayName.trim());
      }
      // A 200 from /auth/login only proves GoTrue accepted the password. The
      // session is only real if the cookies it set survive a round trip and
      // the backend can verify the access token, so confirm before closing
      // the panel (otherwise the next upload fails with a confusing 401).
      const confirmed = await getMe();
      if (!confirmed) {
        setError(copy.authSessionFailed);
        return;
      }
      setPassword("");
      setInvite("");
      onUser(confirmed);
    } catch (cause) {
      setError(friendlyError(cause, language, "auth"));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setBusy(true);
    setError(null);
    try {
      await logout();
      onSignedOut();
    } catch (cause) {
      setError(friendlyError(cause, language, "auth"));
    } finally {
      setBusy(false);
    }
  };

  const field =
    "rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent-500/50";

  return (
    <section aria-label={copy.authTitle} className="mx-auto mt-4 w-full max-w-3xl px-4">
      <div className="animate-fade-up rounded-2xl border border-white/10 bg-white/[0.04] p-4 shadow-glow">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-accent-500/30 bg-accent-500/10">
            <UserRound className="h-4 w-4 text-accent-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">{copy.authTitle}</h2>
            <p className="mt-1 truncate text-xs text-slate-400">
              {user
                ? user.is_guest
                  ? copy.authGuest
                  : (user.email ?? copy.authSignedInAs)
                : copy.authGuestNote}
            </p>
          </div>
          <button
            type="button"
            className="btn h-8 w-8 p-0"
            onClick={onClose}
            aria-label={copy.authClose}
            title={copy.authClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {user ? (
          <div className="mt-4 space-y-3">
            <dl className="grid gap-2 text-xs sm:grid-cols-2">
              <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
                <dt className="text-slate-500">{copy.authEmail}</dt>
                <dd className="mt-0.5 truncate text-slate-200">
                  {user.email ?? "—"}
                </dd>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
                <dt className="text-slate-500">{copy.authRole}</dt>
                <dd className="mt-0.5 text-slate-200">{user.role}</dd>
              </div>
            </dl>

            {user.is_guest ? (
              <p className="flex items-start gap-2 text-[11px] text-slate-500">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {copy.authGuestNote}
              </p>
            ) : null}

            {isAdmin && (
              <button type="button" className="btn" onClick={onManageUsers}>
                <Users className="h-4 w-4" />
                {copy.manageUsers}
              </button>
            )}

            <button
              type="button"
              className="btn"
              onClick={() => void signOut()}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LogOut className="h-4 w-4" />
              )}
              {busy ? copy.authWorking : copy.authSignOut}
            </button>
          </div>
        ) : (
          <>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className={mode === "signin" ? "btn-primary" : "btn"}
                onClick={() => {
                  setMode("signin");
                  setError(null);
                }}
              >
                {copy.authSignIn}
              </button>
              <button
                type="button"
                className={mode === "register" ? "btn-primary" : "btn"}
                onClick={() => {
                  setMode("register");
                  setError(null);
                }}
                disabled={!config.registration}
                title={config.registration ? undefined : copy.authRegistrationClosed}
              >
                {copy.authCreate}
              </button>
            </div>

            {mode === "register" && !config.registration ? (
              <p className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
                {copy.authRegistrationClosed}
              </p>
            ) : null}

            <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={submit}>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                {copy.authEmail}
                <input
                  type="email"
                  className={field}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                  spellCheck={false}
                />
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                {copy.authPassword}
                <input
                  type="password"
                  className={field}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  required
                />
              </label>

              {mode === "register" ? (
                <>
                  {config.invite_required ? (
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      {copy.authInvite}
                      <input
                        className={field}
                        value={invite}
                        onChange={(event) => setInvite(event.target.value)}
                        autoComplete="off"
                        required
                      />
                    </label>
                  ) : null}
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    {copy.authDisplayName}
                    <input
                      className={field}
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      autoComplete="nickname"
                      maxLength={80}
                    />
                  </label>
                </>
              ) : null}

              <div className="flex items-center gap-2 sm:col-span-2">
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={busy || (mode === "register" && !config.registration)}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : mode === "signin" ? (
                    <LogIn className="h-4 w-4" />
                  ) : (
                    <UserPlus className="h-4 w-4" />
                  )}
                  {busy
                    ? copy.authWorking
                    : mode === "signin"
                      ? copy.authSignInAction
                      : copy.authCreateAction}
                </button>
              </div>
            </form>
          </>
        )}

        {error ? (
          <p role="status" className="mt-3 text-xs text-red-300">
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
