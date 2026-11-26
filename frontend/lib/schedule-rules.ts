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

// --- posting times ----------------------------------------------------------------------------

export type Slot = { weekday: number; time: string };

export const WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const MAX_SLOTS = 28;
export const MAX_SLOTS_PER_DAY = 4;

const sameSlot = (a: Slot, b: Slot) => a.weekday === b.weekday && a.time === b.time;
const bySlot = (a: Slot, b: Slot) => a.weekday - b.weekday || a.time.localeCompare(b.time);

/** "19:30"-style 24-hour times only (what `<input type="time">` gives). */
export const isSlotTime = (value: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(value);

/** The slots with one more, in week order; unchanged when it is a duplicate, invalid or over a limit. */
export function addSlot(slots: Slot[], slot: Slot): Slot[] {
  if (!isSlotTime(slot.time) || slots.some((other) => sameSlot(other, slot))) return slots;
  if (slots.length >= MAX_SLOTS) return slots;
  if (slots.filter((other) => other.weekday === slot.weekday).length >= MAX_SLOTS_PER_DAY) return slots;
  return [...slots, slot].sort(bySlot);
}

export const removeSlot = (slots: Slot[], slot: Slot): Slot[] => slots.filter((other) => !sameSlot(other, slot));

/** Every day gets the times of `weekday` (replacing what the other days had). */
export function copyDayToAll(slots: Slot[], weekday: number): Slot[] {
  const times = slots.filter((slot) => slot.weekday === weekday).map((slot) => slot.time);
  return WEEKDAY_LABELS.flatMap((_, day) => times.map((time) => ({ weekday: day, time }))).sort(bySlot);
}

/** "19:30" as the creator's locale writes a time ("7:30 PM"). */
export function slotTimeLabel(time: string, locale?: string): string {
  const [hour, minute] = time.split(":").map(Number);
  return new Date(2000, 0, 1, hour, minute).toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

/** How often the creator posts with these slots: "3 posts a week". */
export function slotsSummary(slots: Slot[]): string {
  if (!slots.length) return "No posting times yet";
  return `${slots.length} post${slots.length === 1 ? "" : "s"} a week`;
}
