/**
 * Decides when to offer BYOK after a *free* answer.
 *
 * This is intentionally a pure function: it has no storage, no network calls and
 * no copy of its own, so the decision can be unit-tested without mounting chat.
 */

export interface ByokHintInput {
  /** Reported by the backend; absent on older backends means deterministic. */
  llmSource?: string;
  confidence: number;
  citationCount: number;
  byokEnabled: boolean;
  keyConfigured: boolean;
}

export const LOW_CONFIDENCE_THRESHOLD = 0.45;

function isDeterministic(source: string | undefined): boolean {
  return source === undefined || source === "" || source === "none";
}

export function shouldSuggestByok(input: ByokHintInput): boolean {
  const {
    llmSource,
    confidence,
    citationCount,
    byokEnabled,
    keyConfigured,
  } = input;

  if (!byokEnabled || keyConfigured) return false;
  if (!isDeterministic(llmSource)) return false;
  if (!Number.isFinite(confidence)) return false;

  return confidence < LOW_CONFIDENCE_THRESHOLD || citationCount <= 0;
}
