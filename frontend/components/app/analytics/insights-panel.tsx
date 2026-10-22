"use client";

import { ChevronDown, EyeOff, Lightbulb, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { errorMessage } from "@/lib/api";
import {
  confidenceText,
  dismissInsight,
  getInsights,
  insightsEmptyText,
  restoreInsight,
  type Insight,
  type Insights,
} from "@/lib/performance";
import { useApi } from "@/lib/use-api";

function Evidence({ insight }: { insight: Insight }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-md text-xs text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
      >
        <ChevronDown aria-hidden="true" className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        Which shorts
      </button>
      {open ? (
        <div className="mt-2 grid gap-3 text-xs sm:grid-cols-2">
          {([["With it", insight.group], ["Your other shorts", insight.comparison]] as const).map(([label, shorts]) => (
            <div key={label}>
              <p className="mb-1 font-medium text-subtle">{label} ({shorts.length})</p>
              <ul className="space-y-0.5">
                {shorts.map((s) => (
                  <li key={s.id} className="truncate">
                    <Link href={`/analytics/${s.id}`} className="text-muted hover:text-foreground">{s.title}</Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function InsightCard({ insight, onChange }: { insight: Insight; onChange: (next: Insight) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      onChange(await (insight.dismissed ? restoreInsight(insight.id) : dismissInsight(insight.id)));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className={`rounded-xl border border-border px-4 py-3 ${insight.dismissed ? "bg-surface opacity-70" : "bg-surface-2"}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-foreground">{insight.statement}</p>
        <Button variant="ghost" size="sm" onClick={toggle} disabled={busy} aria-label={insight.dismissed ? "Show this insight again" : "Hide this insight"}>
          {insight.dismissed ? <RotateCcw aria-hidden="true" /> : <EyeOff aria-hidden="true" />}
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <StatusPill tone={insight.confidence === "moderate" ? "accent" : "neutral"}>{confidenceText(insight)}</StatusPill>
      </div>
      <Evidence insight={insight} />
      {error ? <p className="mt-2 text-xs text-warning">{error}</p> : null}
    </li>
  );
}

function InsightList({ data }: { data: Insights }) {
  const [items, setItems] = useState(data.insights);
  const [showHidden, setShowHidden] = useState(false);
  const replace = (next: Insight) => setItems((all) => all.map((i) => (i.id === next.id ? next : i)));
  const visible = items.filter((i) => !i.dismissed);
  const hidden = items.filter((i) => i.dismissed);
  return (
    <>
      {visible.length ? (
        <ul className="space-y-2">{visible.map((i) => <InsightCard key={i.id} insight={i} onChange={replace} />)}</ul>
      ) : (
        <p className="text-sm text-muted">
          {items.length ? "You hid every insight." : insightsEmptyText(data)}
        </p>
      )}
      {hidden.length ? (
        <div className="mt-3">
          <button type="button" onClick={() => setShowHidden((v) => !v)} className="text-xs text-muted hover:text-foreground">
            {showHidden ? "Hide" : "Show"} {hidden.length} hidden
          </button>
          {showHidden ? <ul className="mt-2 space-y-2">{hidden.map((i) => <InsightCard key={i.id} insight={i} onChange={replace} />)}</ul> : null}
        </div>
      ) : null}
    </>
  );
}

/** Patterns among the creator's own shorts: observed, never causes or predictions. */
export function InsightsPanel() {
  const { data, error, loading, reload } = useApi(getInsights);
  return (
    <section aria-labelledby="insights-heading" className="rounded-xl border border-border bg-surface px-4 py-4">
      <h2 id="insights-heading" className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Lightbulb aria-hidden="true" className="size-4 text-accent-soft" />
        Patterns in your shorts
        {data?.simulated ? <StatusPill tone="warning">Simulated data</StatusPill> : null}
      </h2>
      <p className="mt-1 mb-3 text-xs text-subtle">
        Your shorts compared with each other over their first week. These are associations, not causes: topic, timing and trends differ between shorts too. Nothing here predicts how a short will do.
      </p>
      {loading && !data ? (
        <div role="status" aria-label="Loading insights">
          <Skeleton className="h-16 w-full rounded-xl" />
        </div>
      ) : error || !data ? (
        <ErrorState title="Insights unavailable" message={error ?? "Try again."} onRetry={reload} />
      ) : (
        <InsightList key={data.computed_at} data={data} />
      )}
    </section>
  );
}
