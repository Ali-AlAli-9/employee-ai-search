"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  Building2,
  Check,
  Copy,
  Languages,
  Loader2,
  LogIn,
  LogOut,
  UserPlus,
  UserRound,
} from "lucide-react";

import {
  getMe,
  login,
  logout,
  register,
  type AuthConfig,
  type AuthUser,
  type WorkspaceInfo,
} from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";

type Mode = "signin" | "employer" | "member";

/** Invite links land on `/auth?invite=CODE`; prefill the member field. */
function inviteFromUrl(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("invite") ?? "";
}

/** Split-screen account view backed by the real auth API (no mock credentials). */
export default function AuthView({
  language,
  user,
  config,
  onUser,
  onSignedOut,
  onLanguage,
}: {
  language: Language;
  user: AuthUser | null;
  config: AuthConfig;
  onUser: (user: AuthUser) => void;
  onSignedOut: () => void;
  onLanguage: () => void;
}) {
  const copy = COPY[language];
  // Start from SSR-safe defaults so server and first client render match.
  // The invite (window.location) is applied after mount in the effect below.
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ workspace: WorkspaceInfo; user: AuthUser } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const code = inviteFromUrl();
    if (code) {
      setInvite(code);
      setMode("member");
    }
  }, []);

  const inviteUrl = created
    ? `${typeof window === "undefined" ? "" : window.location.origin}/auth?invite=${encodeURIComponent(created.workspace.invite_code)}`
    : "";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") {
        await login(email.trim(), password);
      } else if (mode === "employer") {
        const result = await register({
          email: email.trim(),
          password,
          kind: "employer",
          workspace_name: workspaceName.trim(),
          display_name: displayName.trim() || undefined,
        });
        const confirmed = await getMe();
        if (!confirmed) {
          setError(copy.authSessionFailed);
          return;
        }
        const workspace = result.workspace ?? confirmed.workspace;
        if (!workspace?.invite_code) {
          setError(copy.authInviteUnavailable);
          return;
        }
        // Keep the employer on this screen until the invite has been copied.
        setPassword("");
        setCreated({ workspace, user: confirmed });
        setCopied(false);
        return;
      } else {
        await register({
          email: email.trim(),
          password,
          kind: "member",
          invite_code: invite.trim(),
          display_name: displayName.trim() || undefined,
        });
      }
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

  const copyInvite = async () => {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
      setError(null);
    } catch {
      setError(copy.authCopyFailed);
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

  const field = "input focus:border-primary-500/60";

  // Two levels: sign in vs. create account, then employer vs. member inside
  // "create account". `mode` still maps directly to the registration kind.
  const registering = mode !== "signin";

  const action =
    mode === "signin"
      ? copy.authSignInAction
      : mode === "employer"
        ? copy.authEmployerAction
        : copy.authMemberAction;

  const roleLabel =
    user?.role === "admin"
      ? copy.adminBadge
      : user?.role === "user"
        ? copy.usersRoleUser
        : user?.role === "viewer"
          ? copy.usersRoleViewer
          : user?.role;

  return (
    <div className="grid min-h-screen bg-app lg:grid-cols-2">
      <section className="relative flex flex-col gap-8 overflow-hidden bg-gradient-to-br from-[#0d1a56] via-[#1e3ac4] to-[#1d4ed8] p-8 text-[#fff] lg:justify-between lg:gap-0 lg:p-10">
        <div className="absolute -start-24 -top-24 h-72 w-72 rounded-full bg-primary-500/40 blur-3xl" />
        <div className="absolute -bottom-32 -end-16 h-80 w-80 rounded-full bg-emerald-500/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#fff]/15 backdrop-blur">
            <BookOpenCheck className="h-5 w-5" />
          </div>
          <span className="text-sm font-semibold tracking-wide">{copy.heroEyebrow}</span>
        </div>
        <div className="relative max-w-lg space-y-5">
          <h1 className="text-3xl font-bold leading-tight lg:text-4xl">{copy.heroTitle}</h1>
          <p className="text-sm leading-relaxed text-[#fff]/90">{copy.heroBody}</p>
          <ul className="space-y-3 text-sm">
            {[BookOpenCheck, Languages].map((Icon, index) => (
              <li
                key={index}
                className="flex items-center gap-3 rounded-xl bg-[#fff]/10 px-3 py-2 ring-1 ring-[#fff]/15 backdrop-blur-sm"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#fff]/15">
                  <Icon className="h-4 w-4" />
                </span>
                {[copy.featureCited, copy.featureRtl][index]}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-md animate-fade-in-up rounded-2xl border border-app bg-surface p-6 shadow-glow">
          <div className="mb-4 flex justify-end">
            <button
              type="button"
              onClick={onLanguage}
              aria-label={copy.language}
              className="btn-secondary flex items-center gap-1.5 px-2.5 py-1.5 text-xs"
            >
              <Languages className="h-3.5 w-3.5" />
              {language === "en" ? "AR" : "EN"}
            </button>
          </div>
          {user ? (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-500/15">
                  <UserRound className="h-5 w-5 text-primary-400" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-primary">{copy.authTitle}</h2>
                  <p className="truncate text-xs text-muted">{user.email ?? copy.authNotProvided}</p>
                </div>
              </div>
              <dl className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg bg-app p-3">
                  <dt className="text-[11px] text-muted">{copy.authEmail}</dt>
                  <dd className="mt-1 truncate text-xs text-primary">
                    {user.email ?? copy.authNotProvided}
                  </dd>
                </div>
                <div className="rounded-lg bg-app p-3">
                  <dt className="text-[11px] text-muted">{copy.authWorkspace}</dt>
                  <dd className="mt-1 truncate text-xs text-primary">
                    {user.workspace?.name ?? copy.authNoWorkspace}
                  </dd>
                </div>
                <div className="rounded-lg bg-app p-3">
                  <dt className="text-[11px] text-muted">{copy.authDisplayName}</dt>
                  <dd className="mt-1 truncate text-xs text-primary">
                    {user.display_name ?? copy.authNotProvided}
                  </dd>
                </div>
                <div className="rounded-lg bg-app p-3">
                  <dt className="text-[11px] text-muted">{copy.authRole}</dt>
                  <dd className="mt-1 text-xs text-primary">{roleLabel}</dd>
                </div>
              </dl>
              <button type="button" className="btn-secondary w-full" onClick={() => void signOut()} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
                {copy.navSignOut}
              </button>
            </div>
          ) : created ? (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/15">
                  <Building2 className="h-5 w-5 text-emerald-300" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-primary">{copy.authInviteCreated}</h2>
                  <p className="text-xs text-muted">{created.workspace.name}</p>
                </div>
              </div>
              <p className="text-xs text-secondary">{copy.authCreatedHint}</p>
              <dl className="space-y-2 rounded-xl bg-app p-3 text-xs">
                <div>
                  <dt className="text-[11px] text-muted">{copy.authInvite}</dt>
                  <dd className="mt-1 break-all font-mono text-primary">{created.workspace.invite_code}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-muted">{copy.authInviteLink}</dt>
                  <dd className="mt-1 break-all text-primary">{inviteUrl}</dd>
                </div>
              </dl>
              <button
                type="button"
                className="btn-secondary w-full"
                onClick={() => void copyInvite()}
                disabled={busy}
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? copy.authCopied : copy.authCopyInvite}
              </button>
              <button
                type="button"
                className="btn-primary w-full"
                onClick={() => onUser(created.user)}
                disabled={busy}
              >
                {copy.authContinue}
                <ArrowRight className="h-4 w-4 flip-rtl" />
              </button>
              {error ? (
                <p role="status" className="text-xs text-red-300">
                  {error}
                </p>
              ) : null}
            </div>
          ) : (
            <>
              <div className="mb-5 space-y-2">
                <div role="tablist" className="flex items-center gap-1.5">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={!registering}
                    className={!registering ? "btn-primary flex-1 px-2" : "btn-secondary flex-1 px-2"}
                    onClick={() => {
                      setMode("signin");
                      setError(null);
                    }}
                  >
                    {copy.authSignIn}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={registering}
                    className={registering ? "btn-primary flex-1 px-2" : "btn-secondary flex-1 px-2"}
                    onClick={() => {
                      // Keep the chosen path when already registering; an invite
                      // link opens straight on "member".
                      if (!registering) setMode(invite.trim() ? "member" : "employer");
                      setError(null);
                    }}
                    disabled={!config.registration}
                    title={!config.registration ? copy.authRegistrationClosed : undefined}
                  >
                    {copy.authCreate}
                  </button>
                </div>
                {registering ? (
                  <div role="tablist" aria-label={copy.authCreate} className="flex items-center gap-1.5">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={mode === "employer"}
                      className={
                        mode === "employer" ? "btn-primary flex-1 px-2" : "btn-secondary flex-1 px-2"
                      }
                      onClick={() => {
                        setMode("employer");
                        setError(null);
                      }}
                    >
                      <Building2 className="me-1 inline h-3.5 w-3.5" />
                      {copy.authEmployer}
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={mode === "member"}
                      className={
                        mode === "member" ? "btn-primary flex-1 px-2" : "btn-secondary flex-1 px-2"
                      }
                      onClick={() => {
                        setMode("member");
                        setError(null);
                      }}
                    >
                      <UserRound className="me-1 inline h-3.5 w-3.5" />
                      {copy.authMember}
                    </button>
                  </div>
                ) : null}
                <p className="text-xs text-muted">
                  {mode === "signin"
                    ? copy.authSignInHint
                    : mode === "employer"
                      ? copy.authEmployerHint
                      : copy.authMemberHint}
                </p>
              </div>

              <form className="space-y-3" onSubmit={submit}>
                {mode === "employer" ? (
                  <label className="block text-xs text-secondary">
                    {copy.authWorkspaceName}
                    <input
                      className={`${field} mt-1`}
                      value={workspaceName}
                      onChange={(event) => setWorkspaceName(event.target.value)}
                      maxLength={80}
                      required
                    />
                  </label>
                ) : null}
                {mode === "member" ? (
                  <label className="block text-xs text-secondary">
                    {copy.authInvite}
                    <input
                      className={`${field} mt-1`}
                      value={invite}
                      onChange={(event) => setInvite(event.target.value)}
                      autoComplete="off"
                      required
                    />
                  </label>
                ) : null}
                {mode !== "signin" ? (
                  <label className="block text-xs text-secondary">
                    {copy.authDisplayName}
                    <input
                      className={`${field} mt-1`}
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      autoComplete="nickname"
                      maxLength={80}
                    />
                  </label>
                ) : null}
                <label className="block text-xs text-secondary">
                  {copy.authEmail}
                  <input
                    type="email"
                    className={`${field} mt-1`}
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    autoComplete="email"
                    required
                  />
                </label>
                <label className="block text-xs text-secondary">
                  {copy.authPassword}
                  <input
                    type="password"
                    className={`${field} mt-1`}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete={mode === "signin" ? "current-password" : "new-password"}
                    required
                  />
                </label>
                <button type="submit" className="btn-primary w-full" disabled={busy}>
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : mode === "signin" ? (
                    <LogIn className="h-4 w-4" />
                  ) : (
                    <UserPlus className="h-4 w-4" />
                  )}
                  {busy ? copy.authWorking : action}
                </button>
              </form>

              {mode === "member" && !invite.trim() ? (
                <p className="mt-3 text-xs text-muted">{copy.authNoInvite}</p>
              ) : null}
              {error ? (
                <p role="status" className="mt-3 text-xs text-red-300">
                  {error}
                </p>
              ) : null}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
