"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, ShieldCheck, Trash2, X } from "lucide-react";

import { verifyLlmKey } from "@/lib/api";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";
import {
  LLM_PROVIDERS,
  clearLlmKey,
  loadLlmKey,
  saveLlmKey,
  type LlmKey,
} from "@/lib/llm";

type Status =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

/**
 * Settings for the visitor's own provider key.
 *
 * The key is read from and saved to sessionStorage only, and the panel states
 * plainly that it transits the API server for each request.
 */
export default function LlmKeyPanel({
  language,
  onClose,
  onSaved,
}: {
  language: Language;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const copy = COPY[language];
  const [providerId, setProviderId] = useState(LLM_PROVIDERS[0].id);
  const [model, setModel] = useState(LLM_PROVIDERS[0].defaultModel);
  const [key, setKey] = useState("");
  const [stored, setStored] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  // sessionStorage only exists in the browser, so it is read after mount to
  // keep the server-rendered markup identical to the first client render.
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
    onSaved?.();
    onClose();
  };

  const forget = () => {
    clearLlmKey();
    setKey("");
    setStored(false);
    setStatus({ kind: "idle" });
    onSaved?.();
  };

  return (
    <div className="w-full rounded-2xl border border-app bg-surface-elevated p-5 shadow-modal sm:p-6">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-accent-500/30 bg-accent-500/10">
          <KeyRound className="h-4 w-4 text-accent-400" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-primary">{copy.llmTitle}</h2>
          <p className="mt-1 text-xs text-secondary">{copy.llmIntro}</p>
        </div>
        <button
          type="button"
          className="btn-ghost h-8 w-8 p-0"
          onClick={onClose}
          aria-label={copy.llmClose}
          title={copy.llmClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
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

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void verify()}
          disabled={status.kind === "checking"}
        >
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
          <button type="button" className="btn-ghost" onClick={forget}>
            <Trash2 className="h-4 w-4" />
            {copy.llmForget}
          </button>
        ) : null}
        {stored ? (
          <span className="text-[11px] text-muted">{copy.llmStored}</span>
        ) : null}
      </div>

      {status.kind === "ok" || status.kind === "error" ? (
        <p
          role="status"
          className={`mt-3 text-xs ${
            status.kind === "ok" ? "text-emerald-300" : "text-red-300"
          }`}
        >
          {status.message}
        </p>
      ) : null}

      <p className="mt-3 flex items-start gap-2 text-[11px] text-muted">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
        {copy.llmWarning}
      </p>
    </div>
  );
}
