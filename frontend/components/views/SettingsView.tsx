"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  Check,
  CheckCircle2,
  KeyRound,
  Languages,
  Loader2,
  LogOut,
  Moon,
  Palette,
  ShieldCheck,
  Sun,
  Trash2,
  UserRound,
} from "lucide-react";

import { verifyLlmKey } from "@/lib/api";
import { logout, type AuthUser } from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";
import {
  LLM_PROVIDERS,
  clearLlmKey,
  loadLlmKey,
  saveLlmKey,
  type LlmKey,
} from "@/lib/llm";
import type { Theme } from "@/lib/theme";

type Status =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

/** Appearance controls plus the real, request-scoped BYOK form. */
export default function SettingsView({
  language,
  onLanguage,
  theme,
  onTheme,
  user,
  byokEnabled,
  onSaved,
  onSignedOut,
}: {
  language: Language;
  onLanguage: (language: Language) => void;
  theme: Theme;
  onTheme: (theme: Theme) => void;
  user: AuthUser | null;
  byokEnabled: boolean;
  onSaved: () => void;
  onSignedOut: () => void;
}) {
  const copy = COPY[language];
  const [providerId, setProviderId] = useState(LLM_PROVIDERS[0].id);
  const [model, setModel] = useState(LLM_PROVIDERS[0].defaultModel);
  const [key, setKey] = useState("");
  const [stored, setStored] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    const saved = loadLlmKey();
    if (!saved) return;
    const match = LLM_PROVIDERS.find((item) => item.baseUrl === saved.baseUrl);
    if (match) setProviderId(match.id);
    setModel(saved.model);
    setKey(saved.key);
    setStored(true);
  }, []);

  const provider =
    LLM_PROVIDERS.find((item) => item.id === providerId) ?? LLM_PROVIDERS[0];

  const draft = (): LlmKey => ({
    key: key.trim(),
    model: model.trim() || provider.defaultModel,
    baseUrl: provider.baseUrl,
  });

  const verify = async () => {
    if (!key.trim()) {
      setStatus({ kind: "error", message: copy.llmKeyRequired });
      return;
    }
    setStatus({ kind: "checking" });
    try {
      const result = await verifyLlmKey(draft());
      const extra = result.models.length ? ` (${result.models.length})` : "";
      setStatus({ kind: "ok", message: `${copy.llmVerified}${extra}` });
    } catch (error) {
      setStatus({
        kind: "error",
        message: friendlyError(error, language, "verify"),
      });
    }
  };

  const save = () => {
    if (!key.trim()) {
      setStatus({ kind: "error", message: copy.llmKeyRequired });
      return;
    }
    saveLlmKey(draft());
    setStored(true);
    onSaved();
    setStatus({ kind: "ok", message: copy.llmStored });
  };

  const forget = () => {
    clearLlmKey();
    setKey("");
    setStored(false);
    setStatus({ kind: "idle" });
    onSaved();
  };

  const signOut = async () => {
    setSigningOut(true);
    try {
      await logout();
      onSignedOut();
    } finally {
      setSigningOut(false);
    }
  };

  const option = (active: boolean) =>
    `flex flex-col items-center gap-2 rounded-xl border p-4 text-center text-xs transition ${
      active
        ? "border-primary-500 bg-primary-500/10 text-primary"
        : "border-white/10 bg-surface/60 text-secondary hover:border-primary-500/40"
    }`;

  return (
    <div className="mx-auto grid w-full max-w-5xl gap-5 p-4 md:p-6 lg:grid-cols-2">
      <section className="card space-y-4 p-5">
        <header className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500/15">
            <Palette className="h-4 w-4 text-primary-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-primary">{copy.appearance}</h2>
            <p className="text-xs text-muted">{copy.viewSettingsSubtitle}</p>
          </div>
        </header>

        <div>
          <p className="mb-2 flex items-center gap-2 text-xs font-medium text-secondary">
            <Sun className="h-3.5 w-3.5" /> {copy.theme}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              className={option(theme === "light")}
              onClick={() => onTheme("light")}
              aria-pressed={theme === "light"}
            >
              <Sun className="h-5 w-5" />
              {copy.themeLight}
              {theme === "light" ? <Check className="h-3.5 w-3.5" /> : null}
            </button>
            <button
              type="button"
              className={option(theme === "dark")}
              onClick={() => onTheme("dark")}
              aria-pressed={theme === "dark"}
            >
              <Moon className="h-5 w-5" />
              {copy.themeDark}
              {theme === "dark" ? <Check className="h-3.5 w-3.5" /> : null}
            </button>
          </div>
        </div>

        <div>
          <p className="mb-2 flex items-center gap-2 text-xs font-medium text-secondary">
            <Languages className="h-3.5 w-3.5" /> {copy.language}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              className={option(language === "en")}
              onClick={() => onLanguage("en")}
              aria-pressed={language === "en"}
            >
              English
              {language === "en" ? <Check className="h-3.5 w-3.5" /> : null}
            </button>
            <button
              type="button"
              className={option(language === "ar")}
              onClick={() => onLanguage("ar")}
              aria-pressed={language === "ar"}
            >
              العربية
              {language === "ar" ? <Check className="h-3.5 w-3.5" /> : null}
            </button>
          </div>
        </div>
      </section>

      <section className="card space-y-4 p-5">
        <header className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500/15">
            <KeyRound className="h-4 w-4 text-primary-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-primary">{copy.llmTitle}</h2>
            <p className="text-xs text-muted">{copy.llmIntro}</p>
          </div>
        </header>

        {byokEnabled ? (
          <>
            {stored && key ? (
              <p className="badge bg-emerald-500/15 text-emerald-300">
                <ShieldCheck className="h-3 w-3" /> {copy.llmStored} · ••••{key.slice(-4)}
              </p>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs text-secondary">
                {copy.llmProvider}
                <select
                  className="input"
                  value={providerId}
                  onChange={(event) => {
                    const next =
                      LLM_PROVIDERS.find((item) => item.id === event.target.value) ??
                      LLM_PROVIDERS[0];
                    setProviderId(next.id);
                    setModel(next.defaultModel);
                    setStatus({ kind: "idle" });
                  }}
                >
                  {LLM_PROVIDERS.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-secondary">
                {copy.llmModel}
                <input
                  className="input"
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  spellCheck={false}
                  autoComplete="off"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-secondary sm:col-span-2">
                {copy.llmKey}
                <input
                  type="password"
                  className="input"
                  value={key}
                  onChange={(event) => {
                    setKey(event.target.value);
                    setStatus({ kind: "idle" });
                  }}
                  placeholder={copy.llmKeyPlaceholder}
                  spellCheck={false}
                  autoComplete="off"
                />
              </label>
            </div>

            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={() => void verify()}>
                {status.kind === "checking" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                {status.kind === "checking" ? copy.llmChecking : copy.llmVerify}
              </button>
              <button type="button" className="btn-primary" onClick={save}>
                {copy.llmSave}
              </button>
              {stored ? (
                <button type="button" className="btn-danger" onClick={forget}>
                  <Trash2 className="h-4 w-4" /> {copy.llmForget}
                </button>
              ) : null}
            </div>

            {status.kind === "ok" || status.kind === "error" ? (
              <p
                role="status"
                className={`text-xs ${
                  status.kind === "ok" ? "text-emerald-300" : "text-red-300"
                }`}
              >
                {status.message}
              </p>
            ) : null}
            <p className="flex items-start gap-2 text-[11px] text-muted">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {copy.llmWarning}
            </p>
          </>
        ) : (
          <p className="rounded-lg bg-amber-500/10 p-3 text-xs text-amber-300">
            {copy.llmFeatureOff}
          </p>
        )}
      </section>

      <section className="card flex items-center gap-3 p-5 lg:col-span-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500/15">
          <UserRound className="h-4 w-4 text-primary-400" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-primary">{copy.authTitle}</h2>
          <p className="truncate text-xs text-secondary">
            {user
              ? (user.email ?? user.display_name ?? copy.authSignedInAs)
              : copy.authSignInHint}
          </p>
          <p className="mt-1 flex items-center gap-1 truncate text-[11px] text-muted">
            <Building2 className="h-3 w-3 shrink-0" />
            {user?.workspace?.name ?? copy.authNoWorkspace}
          </p>
        </div>
        <span className="badge bg-primary-500/15 text-primary-300">
          {user?.role === "admin" ? copy.adminBadge : copy.usersRoleUser}
        </span>
        {user ? (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void signOut()}
            disabled={signingOut}
          >
            {signingOut ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <LogOut className="h-4 w-4" />
            )}
            {copy.navSignOut}
          </button>
        ) : null}
      </section>
    </div>
  );
}
