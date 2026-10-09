// Message times (FR-15): the server's commit instant is absolute (UTC). The client only chooses
// how to render it, in the viewer's timezone by default. Rendering never changes the instant and
// is never used for ordering.

export interface TimeOptions {
  locale?: string;
  /** IANA timezone; defaults to the browser's local timezone. */
  timeZone?: string;
}

function dayKey(date: Date, { locale, timeZone }: TimeOptions): string {
  return new Intl.DateTimeFormat(locale ?? "en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

/**
 * Compact always-visible time: time of day for today, otherwise date and time (with the year if
 * it is not the current one), all in the selected/local timezone.
 */
export function formatMessageTime(
  instant: string,
  now: Date = new Date(),
  options: TimeOptions = {},
): string {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  const { locale, timeZone } = options;
  if (dayKey(date, options) === dayKey(now, options)) {
    return new Intl.DateTimeFormat(locale, { timeZone, hour: "numeric", minute: "2-digit" }).format(
      date,
    );
  }
  const sameYear =
    new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric" }).format(date) ===
    new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric" }).format(now);
  return new Intl.DateTimeFormat(locale, {
    timeZone,
    ...(sameYear ? {} : { year: "numeric" }),
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

/** Precise secondary detail (full date, seconds and zone name) for the same instant. */
export function formatFullTime(instant: string, options: TimeOptions = {}): string {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  return new Intl.DateTimeFormat(options.locale, {
    timeZone: options.timeZone,
    dateStyle: "full",
    timeStyle: "long",
  }).format(date);
}
