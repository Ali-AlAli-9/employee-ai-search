/** Theme helpers shared by the pre-paint script, the toggle and the tests. */

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "eais-theme";

type ThemeReader = Pick<Storage, "getItem"> | null | undefined;
type ThemeWriter = Pick<Storage, "setItem"> | null | undefined;
type ThemeRoot = Pick<HTMLElement, "setAttribute" | "removeAttribute">;

/** Dark is the default; anything unrecognised falls back to it. */
export function readTheme(storage: ThemeReader): Theme {
  try {
    return storage?.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark"; // storage can be disabled in private mode
  }
}

/** Light is an explicit attribute; dark is the stylesheet default. */
export function applyTheme(theme: Theme, root: ThemeRoot): void {
  if (theme === "light") root.setAttribute("data-theme", "light");
  else root.removeAttribute("data-theme");
}

export function storeTheme(theme: Theme, storage: ThemeWriter): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* the toggle still works for this page view */
  }
}

export function toggleTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}
