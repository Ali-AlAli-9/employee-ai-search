/**
 * Visitor-supplied LLM credentials.
 *
 * Stored in sessionStorage on purpose: the key disappears when the tab closes
 * and is not shared with other tabs. localStorage is deliberately not used,
 * because it survives the session and stays exposed to any XSS for longer.
 */

export interface LlmKey {
  key: string;
  model: string;
  baseUrl: string;
}

export interface LlmProvider {
  id: string;
  label: string;
  baseUrl: string;
  defaultModel: string;
}

export interface LlmVerifyResult {
  ok: boolean;
  provider: string;
  model: string;
  checked: "models" | "completion";
  models: string[];
}

export const LLM_PROVIDERS: readonly LlmProvider[] = [
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o-mini",
  },
  {
    id: "groq",
    label: "Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    defaultModel: "llama-3.3-70b-versatile",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "openai/gpt-4o-mini",
  },
];

const STORAGE_KEY = "eais-llm-key";

// The deployment can disable BYOK (LLM_BYOK_ENABLED=false). The health probe
// flips this so a stored key is never sent to an endpoint that would reject it.
let byokAllowed = true;

export function setByokAllowed(value: boolean): void {
  byokAllowed = value;
}

export function loadLlmKey(): LlmKey | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LlmKey>;
    if (typeof parsed.key !== "string" || !parsed.key.trim()) return null;
    const baseUrl =
      typeof parsed.baseUrl === "string" && parsed.baseUrl
        ? parsed.baseUrl
        : LLM_PROVIDERS[0].baseUrl;
    const model =
      typeof parsed.model === "string" && parsed.model
        ? parsed.model
        : LLM_PROVIDERS[0].defaultModel;
    return { key: parsed.key, model, baseUrl };
  } catch {
    return null;
  }
}

export function saveLlmKey(value: LlmKey): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Private mode with storage disabled: the feature simply does not persist.
  }
}

export function clearLlmKey(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/** Headers for requests that may use the visitor's key. */
export function llmHeaders(): Record<string, string> {
  if (!byokAllowed) return {};
  const stored = loadLlmKey();
  if (!stored) return {};
  return {
    "X-LLM-API-Key": stored.key,
    "X-LLM-Model": stored.model,
    "X-LLM-Base-URL": stored.baseUrl,
  };
}

export function maskKey(key: string): string {
  if (key.length <= 8) return "••••";
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}
