"use client";

import { Lightbulb, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { errorMessage } from "@/lib/api";
import {
  getHookIdeas,
  type HookIdeas as Ideas,
  type HookTarget,
  hookTargets,
  kindLabel,
  langOf,
  methodLabel,
  noteText,
} from "@/lib/hooks";

/**
 * Opening hook ideas grounded in the clip: its own sentences first, and — only when the creator
 * picks a language — checked local AI suggestions in that language. Picking one fills the hook
 * text, which the creator can still edit.
 */
export function HookIdeas({
  projectId,
  videoId,
  clipId,
  market,
  language,
  onUse,
}: {
  projectId: string;
  videoId: string;
  clipId: string;
  market: string;
  language: string | null;
  onUse: (text: string) => void;
}) {
  const [target, setTarget] = useState<HookTarget>("original");
  const [data, setData] = useState<Ideas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    getHookIdeas(projectId, videoId, clipId, target)
      .then((ideas) => !cancelled && (setData(ideas), setError(null)))
      .catch((failure) => !cancelled && setError(errorMessage(failure)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [projectId, videoId, clipId, target]);
  const shown = data?.target === target ? data : null;
  const note = shown ? noteText(shown.note) : null;
  return (
    <section aria-labelledby="hook-ideas-heading" className="space-y-3 border-t border-border pt-4">
      <div className="flex items-center gap-2">
        <Lightbulb aria-hidden="true" className="size-4 text-accent-soft" />
        <h3 id="hook-ideas-heading" className="text-sm font-medium">
          Hook ideas
        </h3>
      </div>
      <SegmentedControl
        wrap
        size="sm"
        label="Hook language"
        options={hookTargets(market, language).map((t) => ({ value: t.key, label: t.label }))}
        value={target}
        onChange={(value) => {
          setLoading(true);
          setTarget(value);
        }}
      />
      {loading && !shown ? (
        <p role="status" className="flex items-center gap-2 text-small text-muted">
          <Spinner /> {target === "original" ? "Reading your clip…" : "Asking the local assistant…"}
        </p>
      ) : error ? (
        <p className="text-small text-rose-300">{error}</p>
      ) : shown && shown.ideas.length === 0 ? (
        <p className="text-small text-muted">Your clip has no sentence that works as an opening yet. Write your own above.</p>
      ) : shown ? (
        <ul className="space-y-2">
          {note ? <li className="text-small text-muted">{note}</li> : null}
          {shown.ideas.map((idea) => (
            <li key={`${idea.method}-${idea.text}`} className="rounded-block border border-border bg-surface-2/60 p-3">
              <p dir="auto" lang={langOf(idea)} className="text-sm font-medium text-foreground">
                {idea.text}
              </p>
              {idea.meaning ? <p className="mt-1 text-caption text-muted">Meaning: {idea.meaning}</p> : null}
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <span className="flex flex-wrap items-center gap-x-2 text-caption text-subtle">
                  <span>{kindLabel(idea.kind)}</span>
                  <span aria-hidden="true">·</span>
                  <span className="inline-flex items-center gap-1">
                    {idea.method === "local_ai" ? <Sparkles aria-hidden="true" className="size-3" /> : null}
                    {methodLabel(idea)}
                  </span>
                </span>
                <Button size="sm" variant="secondary" onClick={() => onUse(idea.text)} aria-label={`Use this hook: ${idea.text}`}>
                  Use
                </Button>
              </div>
              {idea.method !== "transcript" ? (
                <details className="mt-1.5 text-caption text-subtle">
                  <summary className="inline-flex cursor-pointer items-center pointer-coarse:min-h-11">Based on your line</summary>
                  <p dir="auto" className="mt-1">
                    {idea.source}
                  </p>
                </details>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
