"use client";

import { Copy, Plus, X } from "lucide-react";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { inputClasses } from "@/components/ui/input-styles";
import { errorMessage } from "@/lib/api";
import { savePostingSlots, type PostingSlots } from "@/lib/publishing";
import {
  MAX_SLOTS_PER_DAY,
  WEEKDAY_LABELS,
  addSlot,
  copyDayToAll,
  isSlotTime,
  removeSlot,
  slotTimeLabel,
  slotsSummary,
  type Slot,
} from "@/lib/schedule-rules";

/** The creator's own time zone, as their browser knows it. */
const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/**
 * Posting times: the weekly slots the creator likes to post at. A preference — PeakSift only
 * offers the next free slot when they schedule a Short; nothing is ever scheduled from it by
 * itself, and posts already scheduled keep their times.
 */
export function PostingTimes({
  current,
  onSaved,
  onClose,
}: {
  current: PostingSlots;
  onSaved: (saved: PostingSlots) => void;
  onClose: () => void;
}) {
  const id = useId();
  const [slots, setSlots] = useState<Slot[]>(current.slots);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const zone = browserZone();
  const movedZone = current.timezone !== null && current.timezone !== zone;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await savePostingSlots(zone, slots));
      onClose();
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-small text-muted">
        Times are in your time zone <span className="text-foreground">({zone})</span>.{" "}
        {movedZone ? `They were saved for ${current.timezone}; saving moves them to ${zone}. ` : ""}
        PeakSift offers the next free one when you schedule a Short — it never posts on its own.
      </p>

      <ul className="space-y-2">
        {WEEKDAY_LABELS.map((label, weekday) => {
          const day = slots.filter((slot) => slot.weekday === weekday);
          const draft = drafts[weekday] ?? "19:00";
          const full = day.length >= MAX_SLOTS_PER_DAY;
          return (
            <li key={label} className="rounded-block border border-border bg-surface-2/60 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="w-24 shrink-0 text-sm font-medium text-foreground">{label}</span>
                <ul className="flex min-w-0 flex-1 flex-wrap gap-1.5" aria-label={`${label} posting times`}>
                  {day.length === 0 ? <li className="text-small text-subtle">No posts</li> : null}
                  {day.map((slot) => (
                    <li key={slot.time}>
                      <span className="inline-flex min-h-8 items-center gap-1 rounded-full border border-accent/35 bg-accent/10 pr-1 pl-2.5 text-small font-medium text-accent-soft">
                        {slotTimeLabel(slot.time)}
                        <button
                          type="button"
                          aria-label={`Remove ${label} ${slotTimeLabel(slot.time)}`}
                          onClick={() => setSlots((previous) => removeSlot(previous, slot))}
                          className="flex size-6 items-center justify-center rounded-full hover:bg-accent/20 focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:size-9"
                        >
                          <X aria-hidden="true" className="size-3.5" />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="flex items-center gap-1.5">
                  <label htmlFor={`${id}-${weekday}`} className="sr-only">
                    New posting time on {label}
                  </label>
                  <input
                    id={`${id}-${weekday}`}
                    type="time"
                    value={draft}
                    disabled={full}
                    onChange={(event) => setDrafts((previous) => ({ ...previous, [weekday]: event.target.value }))}
                    className={`${inputClasses} w-32`}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={full || !isSlotTime(draft)}
                    onClick={() => setSlots((previous) => addSlot(previous, { weekday, time: draft }))}
                  >
                    <Plus aria-hidden="true" />
                    Add
                  </Button>
                </div>
              </div>
              {day.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setSlots((previous) => copyDayToAll(previous, weekday))}
                  className="mt-1.5 inline-flex min-h-8 items-center gap-1.5 rounded text-caption text-muted underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:min-h-11"
                >
                  <Copy aria-hidden="true" className="size-3.5" />
                  Use {label}&apos;s times every day
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>

      <FormError>{error}</FormError>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-small text-muted" aria-live="polite">
          {slotsSummary(slots)}
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save posting times"}
          </Button>
        </div>
      </div>
    </div>
  );
}
