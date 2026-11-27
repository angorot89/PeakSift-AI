"use client";

import { Download, Play, RotateCcw, Smartphone } from "lucide-react";
import { buttonClasses } from "@/components/ui/button-styles";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/progress";
import { StatusPill } from "@/components/ui/status-pill";
import {
  captionSummary,
  describeEdit,
  editContentUrl,
  editDownloadUrl,
  isEditActive,
  layoutLabel,
  type ClipEdit,
} from "@/lib/edits";
import { audioFromConfiguration, audioSummary } from "@/lib/audio-mix";
import { cutsFromConfiguration } from "@/lib/cuts";
import { formatDuration } from "@/lib/format";

function VersionStatus({ edit }: { edit: ClipEdit }) {
  if (edit.status === "ready") return <StatusPill tone="success">Ready</StatusPill>;
  if (edit.status === "failed") return <StatusPill tone="danger">Failed</StatusPill>;
  if (edit.is_stale) return <StatusPill tone="warning">Stalled</StatusPill>;
  const stage = edit.status === "queued" ? "Queued" : edit.status === "validating" ? "Validating" : "Rendering";
  return (
    <StatusPill tone="processing">
      {stage}
      {edit.progress_percent > 0 && edit.status !== "queued" ? <span className="tabular"> · {edit.progress_percent}%</span> : null}
    </StatusPill>
  );
}

/**
 * Every rendered (or rendering) version of this clip, named by its settings — never by id.
 * Selecting a ready version shows the actual rendered MP4 on the stage.
 */
export function VersionList({
  edits,
  selectedId,
  onSelect,
  onRetry,
  retryingId,
}: {
  edits: ClipEdit[];
  selectedId: string | null;
  onSelect: (edit: ClipEdit) => void;
  onRetry: (edit: ClipEdit) => void;
  retryingId: string | null;
}) {
  return (
    <ul className="space-y-2" aria-label="Versions">
      {edits.map((edit) => {
        const ready = edit.status === "ready";
        const stuck = edit.status === "failed" || (isEditActive(edit.status) && edit.is_stale);
        const selected = selectedId === edit.id;
        const name = describeEdit(edit);
        const audio = audioSummary(audioFromConfiguration(edit.configuration));
        return (
          <li
            key={edit.id}
            aria-label={`Version: ${name}`}
            className={`flex items-center gap-3 rounded-block border p-2.5 transition-colors ${
              selected ? "border-accent/60 bg-accent/[0.05]" : "border-border bg-surface-2/50"
            }`}
          >
            <span className="relative flex h-14 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-black text-subtle">
              {ready ? (
                <video
                  aria-hidden="true"
                  tabIndex={-1}
                  muted
                  preload="metadata"
                  src={`${editContentUrl(edit.id)}#t=1`}
                  className="size-full object-cover"
                />
              ) : isEditActive(edit.status) && !edit.is_stale ? (
                <Spinner className="size-3.5" />
              ) : (
                <Smartphone aria-hidden="true" className="size-3.5" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">{layoutLabel(edit.layout)}</p>
              <p className="truncate text-xs text-muted">
                {captionSummary(edit)}
                {audio ? ` · ${audio}` : ""}
                {cutsFromConfiguration(edit.configuration).length ? " · Tightened" : ""}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <VersionStatus edit={edit} />
                {ready && edit.duration_seconds != null ? (
                  <span className="tabular text-xs text-subtle">{formatDuration(edit.duration_seconds)}</span>
                ) : null}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {ready ? (
                <>
                  <Button
                    variant={selected ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => onSelect(edit)}
                    aria-pressed={selected}
                    aria-label={`Play version: ${name}`}
                  >
                    <Play aria-hidden="true" />
                    <span className="hidden sm:inline">{selected ? "Playing" : "Play"}</span>
                  </Button>
                  <a
                    href={editDownloadUrl(edit.id)}
                    download
                    className={buttonClasses("ghost", "sm", "px-2")}
                    aria-label={`Download short — ${name}`}
                  >
                    <Download aria-hidden="true" />
                  </a>
                </>
              ) : stuck ? (
                <Button variant="secondary" size="sm" onClick={() => onRetry(edit)} disabled={retryingId === edit.id} aria-label={`Retry render: ${name}`}>
                  <RotateCcw aria-hidden="true" />
                  {retryingId === edit.id ? "Retrying…" : "Retry"}
                </Button>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
