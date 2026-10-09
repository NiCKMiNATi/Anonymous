import { describe, expect, it } from "vitest";
import { formatFullTime, formatMessageTime } from "./time";

const INSTANT = "2026-03-10T23:30:00.000000Z";
const NOW_SAME_DAY_UTC = new Date("2026-03-10T23:45:00Z");

describe("formatMessageTime", () => {
  it("renders the same absolute instant differently per timezone without changing it", () => {
    const utc = formatMessageTime(INSTANT, NOW_SAME_DAY_UTC, { locale: "en-US", timeZone: "UTC" });
    const denver = formatMessageTime(INSTANT, NOW_SAME_DAY_UTC, {
      locale: "en-US",
      timeZone: "America/Denver",
    });
    const tokyo = formatMessageTime(INSTANT, NOW_SAME_DAY_UTC, {
      locale: "en-US",
      timeZone: "Asia/Tokyo",
    });
    expect(utc).toBe("11:30 PM");
    expect(denver).toBe("5:30 PM"); // UTC-6 on this date (MDT starts 2026-03-08)
    expect(tokyo).toBe("8:30 AM"); // already Mar 11 in Tokyo, but "now" is also Mar 11 there
    expect(INSTANT).toBe("2026-03-10T23:30:00.000000Z"); // the instant itself is untouched
  });

  it("decides what 'today' means in the selected timezone, not the viewer's UTC day", () => {
    const earlier = "2026-03-10T10:00:00Z"; // Mar 10 in UTC, Mar 10 19:00 in Tokyo
    const text = formatMessageTime(earlier, NOW_SAME_DAY_UTC, {
      locale: "en-US",
      timeZone: "Asia/Tokyo", // now is Mar 11 08:45 in Tokyo, so this is the previous local day
    });
    expect(text).toBe("Mar 10, 7:00 PM");
  });

  it("shows the date when the message is not from today in the selected timezone", () => {
    const text = formatMessageTime("2026-03-09T12:00:00Z", NOW_SAME_DAY_UTC, {
      locale: "en-US",
      timeZone: "UTC",
    });
    expect(text).toBe("Mar 9, 12:00 PM");
  });

  it("includes the year only when it differs from the current year", () => {
    const text = formatMessageTime("2025-12-31T12:00:00Z", NOW_SAME_DAY_UTC, {
      locale: "en-US",
      timeZone: "UTC",
    });
    expect(text).toContain("2025");
  });

  it("handles a date boundary: the same instant is on different local days", () => {
    const instant = "2026-01-01T00:30:00Z";
    const now = new Date("2026-01-01T12:00:00Z");
    const losAngeles = formatMessageTime(instant, now, {
      locale: "en-US",
      timeZone: "America/Los_Angeles",
    });
    const utc = formatMessageTime(instant, now, { locale: "en-US", timeZone: "UTC" });
    expect(losAngeles).toContain("Dec 31"); // 4:30 PM the previous local day
    expect(losAngeles).toContain("2025");
    expect(utc).toBe("12:30 AM");
  });

  it("does not throw on an invalid instant", () => {
    expect(formatMessageTime("not a date")).toBe("Unknown time");
    expect(formatFullTime("not a date")).toBe("Unknown time");
  });
});

describe("formatFullTime", () => {
  it("gives precise detail including the zone for the same instant", () => {
    const full = formatFullTime("2026-03-10T23:30:15Z", { locale: "en-US", timeZone: "UTC" });
    expect(full).toContain("March 10, 2026");
    expect(full).toContain("11:30:15 PM");
    expect(full).toMatch(/UTC/);
  });
});
