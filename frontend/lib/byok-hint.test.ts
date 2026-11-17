import { describe, expect, it } from "vitest";

import {
  LOW_CONFIDENCE_THRESHOLD,
  shouldSuggestByok,
  type ByokHintInput,
} from "./byok-hint";
import { COPY } from "./copy";

const base: ByokHintInput = {
  llmSource: "none",
  confidence: 0.7,
  citationCount: 2,
  byokEnabled: true,
  keyConfigured: false,
};

describe("BYOK smart hint", () => {
  it("uses a documented low-confidence threshold", () => {
    expect(LOW_CONFIDENCE_THRESHOLD).toBe(0.45);
  });

  it("suggests a key for a low-confidence deterministic answer", () => {
    expect(shouldSuggestByok({ ...base, confidence: 0.44 })).toBe(true);
    expect(shouldSuggestByok({ ...base, confidence: LOW_CONFIDENCE_THRESHOLD })).toBe(false);
  });

  it("suggests a key when deterministic evidence is missing", () => {
    expect(shouldSuggestByok({ ...base, citationCount: 0 })).toBe(true);
  });

  it("treats an older backend without llm_source as deterministic", () => {
    expect(shouldSuggestByok({ ...base, llmSource: undefined, citationCount: 0 })).toBe(true);
    expect(shouldSuggestByok({ ...base, llmSource: undefined })).toBe(false);
  });

  it("does not suggest a key when a model already answered", () => {
    expect(shouldSuggestByok({ ...base, llmSource: "user", confidence: 0.1, citationCount: 0 })).toBe(false);
    expect(shouldSuggestByok({ ...base, llmSource: "server", confidence: 0.1, citationCount: 0 })).toBe(false);
  });

  it("respects key and deployment state", () => {
    expect(shouldSuggestByok({ ...base, keyConfigured: true, citationCount: 0 })).toBe(false);
    expect(shouldSuggestByok({ ...base, byokEnabled: false, citationCount: 0 })).toBe(false);
  });

  it("ignores invalid confidence values", () => {
    expect(shouldSuggestByok({ ...base, confidence: Number.NaN })).toBe(false);
  });

  it("has localized, key-focused copy", () => {
    expect(COPY.en.byokHint.toLowerCase()).toContain("key");
    expect(COPY.ar.byokHint).toContain("مفتاح");
  });
});
