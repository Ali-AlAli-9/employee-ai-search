import type { Language } from "./copy";

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

/** Compact, locale-neutral file size used by the library and document lists. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";

  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }

  const rounded = unit === 0 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${BYTE_UNITS[unit]}`;
}

/** Coarse relative time with deterministic, locally authored labels. */
export function timeAgo(value: string | null, language: Language): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return language === "ar" ? "الآن" : "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return language === "ar" ? `منذ ${minutes} دقيقة` : `${minutes} min ago`;
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return language === "ar" ? `منذ ${hours} ساعة` : `${hours} hr ago`;
  }

  const days = Math.floor(hours / 24);
  return language === "ar" ? `منذ ${days} يوم` : `${days} days ago`;
}
