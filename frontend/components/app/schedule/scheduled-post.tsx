"use client";

import { CalendarClock, Send, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { inputClasses } from "@/components/ui/input-styles";
import { errorMessage } from "@/lib/api";
import { cancelPost, publishPostNow, reschedulePost, type PublishJob } from "@/lib/publishing";
import { fromLocalInput, timeProblem, toLocalInput } from "@/lib/schedule-rules";

/** "Fri, Nov 27, 7:30 PM" in the creator's own locale and time zone. */
export function formatWhen(when: Date): string {
  return when.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

type Step = "idle" | "moving" | "confirm-now" | "confirm-cancel";

/**
 * A post that is waiting for its time: move it, publish it now, or cancel it. Each of the two
 * actions that cannot be undone asks once before it happens.
 */
export function ScheduledPost({
  job,
  onChange,
  onCancelled,
  compact = false,
}: {
  job: PublishJob;
  /** The post changed (moved, or released to publish now). */
  onChange: (job: PublishJob) => void;
  onCancelled: () => void;
  /** On the calendar: no heading, smaller buttons. */
  compact?: boolean;
}) {
  const inputId = useId();
  const when = job.scheduled_at ? new Date(job.scheduled_at) : null;
  const [step, setStep] = useState<Step>("idle");
  const [value, setValue] = useState(when ? toLocalInput(when) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const size = compact ? "sm" : "md";

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setStep("idle");
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  const problem = step === "moving" ? timeProblem(value, new Date()) : null;

  return (
    <div className="space-y-3">
      {!compact && when ? (
        <p className="flex items-center gap-2 text-sm text-foreground">
          <CalendarClock aria-hidden="true" className="size-4 shrink-0 text-accent-soft" />
          <span>
            Scheduled for <time dateTime={when.toISOString()}>{formatWhen(when)}</time>
          </span>
        </p>
      ) : null}

      {step === "idle" ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size={size} onClick={() => setStep("moving")}>
            <CalendarClock aria-hidden="true" />
            Change time
          </Button>
          <Button variant="secondary" size={size} onClick={() => setStep("confirm-now")}>
            <Send aria-hidden="true" />
            Publish now
          </Button>
          <Button variant="ghost" size={size} onClick={() => setStep("confirm-cancel")}>
            <Trash2 aria-hidden="true" />
            Cancel post
          </Button>
        </div>
      ) : null}

      {step === "moving" ? (
        <div className="space-y-2">
          <label htmlFor={inputId} className="block text-small font-medium text-foreground">
            New time <span className="font-normal text-subtle">(your local time)</span>
          </label>
          <input
            id={inputId}
            type="datetime-local"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            aria-invalid={problem ? true : undefined}
            className={`${inputClasses} max-w-64`}
          />
          {problem ? <p className="text-small text-rose-300">{problem}</p> : null}
          <div className="flex flex-wrap gap-2">
            <Button
              size={size}
              disabled={busy || Boolean(problem)}
              onClick={() =>
                run(async () => {
                  const next = fromLocalInput(value);
                  if (next) onChange(await reschedulePost(job.id, next.toISOString()));
                })
              }
            >
              {busy ? "Saving…" : "Save time"}
            </Button>
            <Button variant="ghost" size={size} disabled={busy} onClick={() => setStep("idle")}>
              Back
            </Button>
          </div>
        </div>
      ) : null}

      {step === "confirm-now" ? (
        <div className="space-y-2">
          <p className="text-small text-muted">Publish “{job.title}” to YouTube now instead of waiting?</p>
          <div className="flex flex-wrap gap-2">
            <Button size={size} disabled={busy} onClick={() => run(async () => onChange(await publishPostNow(job.id)))}>
              <Send aria-hidden="true" />
              {busy ? "Starting…" : "Yes, publish now"}
            </Button>
            <Button variant="ghost" size={size} disabled={busy} onClick={() => setStep("idle")}>
              Keep it scheduled
            </Button>
          </div>
        </div>
      ) : null}

      {step === "confirm-cancel" ? (
        <div className="space-y-2">
          <p className="text-small text-muted">Cancel this post? Nothing has been uploaded; your Short stays ready.</p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="danger"
              size={size}
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await cancelPost(job.id);
                  onCancelled();
                })
              }
            >
              {busy ? "Cancelling…" : "Yes, cancel it"}
            </Button>
            <Button variant="ghost" size={size} disabled={busy} onClick={() => setStep("idle")}>
              Keep it scheduled
            </Button>
          </div>
        </div>
      ) : null}

      <FormError>{error}</FormError>
    </div>
  );
}
