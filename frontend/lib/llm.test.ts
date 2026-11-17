import { beforeEach, describe, expect, it } from "vitest";

import {
  clearLlmKey,
  llmHeaders,
  loadLlmKey,
  maskKey,
  saveLlmKey,
  setByokAllowed,
} from "./llm";

const credential = {
  key: "sk-abcdefghijklmnop",
  model: "gpt-4o-mini",
  baseUrl: "https://api.openai.com/v1",
};

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  setByokAllowed(true);
});

describe("visitor-supplied LLM key", () => {
  it("round trips through sessionStorage only", () => {
    saveLlmKey(credential);

    expect(loadLlmKey()).toEqual(credential);
    expect(window.localStorage.length).toBe(0);
  });

  it("is removed on clear", () => {
    saveLlmKey(credential);
    clearLlmKey();
    expect(loadLlmKey()).toBeNull();
  });

  it("rejects empty and corrupt entries", () => {
    window.sessionStorage.setItem("eais-llm-key", JSON.stringify({ key: "  " }));
    expect(loadLlmKey()).toBeNull();

    window.sessionStorage.setItem("eais-llm-key", "{not json");
    expect(loadLlmKey()).toBeNull();
  });

  it("masks the key in the UI", () => {
    expect(maskKey("sk-abcdefghijklmnop")).toBe("sk-a…mnop");
    expect(maskKey("short")).toBe("••••");
  });

  it("attaches headers only when BYOK is allowed and a key exists", () => {
    expect(llmHeaders()).toEqual({});

    saveLlmKey(credential);
    expect(llmHeaders()).toEqual({
      "X-LLM-API-Key": credential.key,
      "X-LLM-Model": credential.model,
      "X-LLM-Base-URL": credential.baseUrl,
    });

    setByokAllowed(false);
    expect(llmHeaders()).toEqual({});
  });
});
