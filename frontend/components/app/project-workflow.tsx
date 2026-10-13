"use client";

import { AlertTriangle, Check } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { WORKFLOW_STEPS, type WorkflowStepKey } from "@/components/app/workflow-steps";
import { Spinner } from "@/components/ui/progress";

/** What a section knows about its own stage. "unknown" = still loading (shown as pending). */
export type StepState = "unknown" | "todo" | "active" | "done" | "failed";

type Ctx = {
  states: Record<WorkflowStepKey, StepState>;
  report: (key: WorkflowStepKey, state: StepState) => void;
};

const INITIAL: Record<WorkflowStepKey, StepState> = {
  upload: "unknown",
  transcribe: "unknown",
  detect: "unknown",
  generate: "unknown",
  edit: "unknown",
};

const WorkflowContext = createContext<Ctx | null>(null);

/** Each section reports its real state; the stepper only reflects what the API said. */
export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [states, setStates] = useState(INITIAL);
  const report = useCallback((key: WorkflowStepKey, state: StepState) => {
    setStates((previous) => (previous[key] === state ? previous : { ...previous, [key]: state }));
  }, []);
  const value = useMemo(() => ({ states, report }), [states, report]);
  return <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>;
}

/** Report this section's stage while it is mounted (no-op outside a project page). */
export function useWorkflowReport(key: WorkflowStepKey, state: StepState) {
  const report = useContext(WorkflowContext)?.report;
  useEffect(() => {
    report?.(key, state);
  }, [report, key, state]);
}

/** The raw reporter, for a parent that reports on behalf of sections it has not mounted. */
export function useWorkflowReporter() {
  return useContext(WorkflowContext)?.report ?? null;
}

const ANCHORS: Record<WorkflowStepKey, string> = {
  upload: "source",
  transcribe: "transcript",
  detect: "clips",
  generate: "generated",
  edit: "generated",
};

const STATE_WORDS: Record<StepState | "next", string> = {
  unknown: "Checking",
  todo: "Not started",
  next: "Next",
  active: "In progress",
  done: "Done",
  failed: "Needs attention",
};

/**
 * A compact, non-blocking workflow indicator: where this project is and what comes next.
 * Every step is a plain link to its section; nothing is locked.
 */
export function WorkflowStepper() {
  const ctx = useContext(WorkflowContext);
  if (!ctx) return null;
  const { states } = ctx;
  // "Next" is the first step that is not done, once everything before it is done.
  const nextKey = WORKFLOW_STEPS.find((step) => states[step.key] !== "done")?.key;

  return (
    <nav aria-label="Project workflow" className="mt-6">
      <ol className="grid grid-cols-5 gap-1 rounded-2xl border border-border bg-surface p-1.5 sm:gap-1.5">
        {WORKFLOW_STEPS.map((step, index) => {
          const raw = states[step.key];
          const isNext = step.key === nextKey && (raw === "todo" || raw === "unknown");
          const shown: StepState | "next" = isNext && raw === "todo" ? "next" : raw;
          const tone =
            shown === "done"
              ? "bg-success/15 text-success"
              : shown === "active"
                ? "bg-accent/15 text-accent-soft"
                : shown === "failed"
                  ? "bg-danger/15 text-danger"
                  : shown === "next"
                    ? "bg-accent/15 text-accent-soft ring-1 ring-accent/50"
                    : "bg-surface-3 text-subtle";
          return (
            <li key={step.key} className="min-w-0">
              <a
                href={`#${ANCHORS[step.key]}`}
                aria-current={shown === "next" || shown === "active" ? "step" : undefined}
                className={`flex h-full min-w-0 flex-col items-center gap-1.5 rounded-xl px-1 py-2 text-center transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:flex-row sm:gap-2.5 sm:px-2.5 sm:text-left ${
                  shown === "next" || shown === "active" ? "bg-surface-2" : ""
                }`}
              >
                <span className={`flex size-7 shrink-0 items-center justify-center rounded-full ${tone}`}>
                  {shown === "done" ? (
                    <Check aria-hidden="true" className="size-3.5" strokeWidth={3} />
                  ) : shown === "active" ? (
                    <Spinner className="size-3.5" />
                  ) : shown === "failed" ? (
                    <AlertTriangle aria-hidden="true" className="size-3.5" />
                  ) : (
                    <step.icon aria-hidden="true" className="size-3.5" />
                  )}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[11px] font-medium text-foreground sm:text-sm">
                    <span className="sr-only">Step {index + 1}: </span>
                    {step.label}
                  </span>
                  <span
                    className={`hidden truncate text-xs sm:block ${
                      shown === "failed" ? "text-rose-200" : shown === "next" ? "text-accent-soft" : "text-subtle"
                    }`}
                  >
                    {STATE_WORDS[shown]}
                  </span>
                  <span className="sr-only sm:hidden">, {STATE_WORDS[shown]}</span>
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
