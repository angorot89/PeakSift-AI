// Schedule & Post (pure rules, no React): the week on the calendar, the creator's local time
// in a datetime-local input, and the words for a post's state. Unit-tested with node --test.
// Times are always the creator's local time on screen and ISO-with-zone on the wire.

export const MIN_LEAD_MINUTES = 5; // the server refuses anything under 2 minutes; leave room to type
export const MAX_AHEAD_DAYS = 365;

const pad = (value: number) => String(value).padStart(2, "0");

/** Monday 00:00 (local) of the week `date` is in. */
export function weekStart(date: Date): Date {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return start;
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/** The seven days of the week starting at `start` (each at local midnight). */
export const weekDays = (start: Date): Date[] => Array.from({ length: 7 }, (_, index) => addDays(start, index));

/** A local calendar day as `2026-11-26` (for keys and `<time dateTime>`). */
export const dayKey = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

export const isSameDay = (a: Date, b: Date) => dayKey(a) === dayKey(b);

/** Items grouped by the local day of `at`, each day sorted by time. Days without items are absent. */
export function groupByDay<T extends { at: string }>(items: T[]): Map<string, T[]> {
  const days = new Map<string, T[]>();
  for (const item of [...items].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())) {
    const key = dayKey(new Date(item.at));
    days.set(key, [...(days.get(key) ?? []), item]);
  }
  return days;
}

/** A Date as the value of `<input type="datetime-local">` (local time, minutes). */
export const toLocalInput = (date: Date) =>
  `${dayKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;

/** The Date a datetime-local value means in the creator's zone, or null when it is not one. */
export function fromLocalInput(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match.map(Number);
  const date = new Date(year, month - 1, day, hour, minute);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** A sensible first suggestion: the next full hour that is at least an hour away. */
export function suggestedTime(now: Date): Date {
  const next = new Date(now);
  next.setMinutes(0, 0, 0);
  next.setHours(next.getHours() + 2);
  return next;
}

/** Why a chosen time cannot be used, or null when it can. */
export function timeProblem(value: string, now: Date): string | null {
  const when = fromLocalInput(value);
  if (!when) return "Pick a date and time.";
  const lead = (when.getTime() - now.getTime()) / 60000;
  if (lead < MIN_LEAD_MINUTES) return "Pick a time at least a few minutes from now, or publish now.";
  if (lead > MAX_AHEAD_DAYS * 24 * 60) return "Pick a time within the next year.";
  return null;
}

/** "Nov 23 – 29" or "Nov 30 – Dec 6" for the week starting at `start`. */
export function weekLabel(start: Date, locale?: string): string {
  const end = addDays(start, 6);
  const month = (date: Date) => date.toLocaleDateString(locale, { month: "short" });
  const sameMonth = start.getMonth() === end.getMonth();
  return `${month(start)} ${start.getDate()} – ${sameMonth ? "" : `${month(end)} `}${end.getDate()}`;
}

export type PostTone = "scheduled" | "working" | "done" | "attention";

/** How a post reads on the calendar. Never "published" before YouTube has the video. */
export function postState(job: {
  status: string;
  is_stale: boolean;
  error_code: string | null;
}): { label: string; tone: PostTone } {
  if (job.is_stale) return { label: "Stalled", tone: "attention" };
  switch (job.status) {
    case "scheduled":
      return { label: "Scheduled", tone: "scheduled" };
    case "queued":
    case "preparing":
    case "uploading":
      return { label: "Publishing", tone: "working" };
    case "uploaded":
    case "processing":
      return { label: "On YouTube", tone: "done" };
    case "published":
      return { label: "Published", tone: "done" };
    case "failed":
      return { label: job.error_code === "schedule_missed" ? "Missed" : "Not published", tone: "attention" };
    default:
      return { label: "Not published", tone: "attention" };
  }
}
