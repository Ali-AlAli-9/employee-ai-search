import { describe, expect, it } from "vitest";

import { formatBytes, timeAgo } from "./format";

describe("formatBytes", () => {
  it("formats zero, negative and invalid values as 0 B", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(-5)).toBe("0 B");
    expect(formatBytes(Number.NaN)).toBe("0 B");
  });

  it("keeps byte counts under 1 KB exact", () => {
    expect(formatBytes(999)).toBe("999 B");
  });

  it("scales through KB, MB and GB with one decimal", () => {
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1024 * 1024)).toBe("1 MB");
    expect(formatBytes(2.5 * 1024 * 1024 * 1024)).toBe("2.5 GB");
  });
});

describe("timeAgo", () => {
  it("renders missing and invalid dates as a dash", () => {
    expect(timeAgo(null, "en")).toBe("—");
    expect(timeAgo("not-a-date", "en")).toBe("—");
  });

  it("renders recent, minute, hour and day buckets in English", () => {
    const now = Date.now();
    expect(timeAgo(new Date(now - 5_000).toISOString(), "en")).toBe("just now");
    expect(timeAgo(new Date(now - 5 * 60_000).toISOString(), "en")).toBe("5 min ago");
    expect(timeAgo(new Date(now - 3 * 3_600_000).toISOString(), "en")).toBe("3 hr ago");
    expect(timeAgo(new Date(now - 2 * 86_400_000).toISOString(), "en")).toBe("2 days ago");
  });

  it("renders localized buckets in Arabic", () => {
    const now = Date.now();
    expect(timeAgo(new Date(now - 5_000).toISOString(), "ar")).toBe("الآن");
    expect(timeAgo(new Date(now - 5 * 60_000).toISOString(), "ar")).toBe("منذ 5 دقيقة");
    expect(timeAgo(new Date(now - 3 * 3_600_000).toISOString(), "ar")).toBe("منذ 3 ساعة");
    expect(timeAgo(new Date(now - 2 * 86_400_000).toISOString(), "ar")).toBe("منذ 2 يوم");
  });
});
