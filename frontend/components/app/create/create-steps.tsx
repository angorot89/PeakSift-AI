import { Check } from "lucide-react";

export const CREATE_STEPS = ["Start", "Style", "Review", "Render"] as const;

/** Where the creator is in making a Short: Start → Style → Review → Render. */
export function CreateSteps({ current }: { current: number }) {
  return (
    <ol aria-label="Making a Short" className="flex flex-wrap items-center gap-x-2 gap-y-1 text-small">
      {CREATE_STEPS.map((step, index) => {
        const done = index < current;
        const now = index === current;
        return (
          <li key={step} aria-current={now ? "step" : undefined} className="flex items-center gap-2">
            <span
              className={`flex size-6 items-center justify-center rounded-full text-caption font-semibold ${
                done ? "bg-success/15 text-emerald-200" : now ? "bg-accent text-background" : "bg-surface-3 text-subtle"
              }`}
            >
              {done ? <Check aria-hidden="true" className="size-3" strokeWidth={3} /> : index + 1}
            </span>
            {/* On phones only the current step is named; the numbers carry the rest. */}
            <span className={now ? "font-medium text-foreground" : `max-sm:sr-only ${done ? "text-muted" : "text-subtle"}`}>
              {step}
              <span className="sr-only">{done ? " (done)" : now ? " (current step)" : ""}</span>
            </span>
            {index < CREATE_STEPS.length - 1 ? <span aria-hidden="true" className="h-px w-4 bg-border-strong sm:w-8" /> : null}
          </li>
        );
      })}
    </ol>
  );
}
