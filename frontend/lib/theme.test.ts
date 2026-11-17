import { describe, expect, it } from "vitest";

import {
  THEME_STORAGE_KEY,
  applyTheme,
  readTheme,
  storeTheme,
  toggleTheme,
} from "./theme";

function storage(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => {
      data[key] = value;
    },
    data,
  };
}

function root() {
  let value: string | null = null;
  return {
    setAttribute: (name: string, next: string) => {
      if (name === "data-theme") value = next;
    },
    removeAttribute: (name: string) => {
      if (name === "data-theme") value = null;
    },
    get value() {
      return value;
    },
  };
}

describe("theme persistence", () => {
  it("defaults to dark when nothing is stored", () => {
    expect(readTheme(storage())).toBe("dark");
  });

  it("reads a stored light theme", () => {
    expect(readTheme(storage({ [THEME_STORAGE_KEY]: "light" }))).toBe("light");
  });

  it("ignores unknown stored values", () => {
    expect(readTheme(storage({ [THEME_STORAGE_KEY]: "neon" }))).toBe("dark");
  });

  it("survives storage that throws (private mode)", () => {
    const broken = {
      getItem: () => {
        throw new Error("storage disabled");
      },
      setItem: () => {
        throw new Error("storage disabled");
      },
    };
    expect(readTheme(broken)).toBe("dark");
    expect(() => storeTheme("light", broken)).not.toThrow();
  });

  it("applies light as an attribute and dark by removing it", () => {
    const element = root();
    applyTheme("light", element);
    expect(element.value).toBe("light");
    applyTheme("dark", element);
    expect(element.value).toBeNull();
  });

  it("stores the chosen theme under the shared key", () => {
    const saved = storage();
    storeTheme("light", saved);
    expect(saved.data[THEME_STORAGE_KEY]).toBe("light");
  });

  it("toggles both ways", () => {
    expect(toggleTheme("dark")).toBe("light");
    expect(toggleTheme("light")).toBe("dark");
  });
});
