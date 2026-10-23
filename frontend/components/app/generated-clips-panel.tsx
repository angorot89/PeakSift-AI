"use client";

import { Clapperboard, Download, Smartphone, Wand2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EmptyState, LoadingState } from "@/components/app/states";
import { buttonClasses } from "@/components/ui/button-styles";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { clipContentUrl, clipDownloadUrl, type GeneratedClip } from "@/lib/clips";
import { createHref, editorHref, isEditActive, listEdits } from "@/lib/edits";
import { formatDuration, formatTimestamp } from "@/lib/format";

type ShortCounts = { ready: number; active: number };

function ClipStatus({ clip }: { clip: GeneratedClip }) {
  if (clip.status === "ready") return <StatusPill tone="success">Ready</StatusPill>;
  if (clip.status === "failed") return <StatusPill tone="danger">Failed</StatusPill>;
  if (clip.is_stale) return <StatusPill tone="warning">Stalled</StatusPill>;
  return <StatusPill tone="processing">Rendering</StatusPill>;
}

function ClipRow({ clip, shorts, projectId }: { clip: GeneratedClip; shorts: ShortCounts | undefined; projectId: string }) {
  const ready = clip.status === "ready";
  return (
    <li className="flex flex-col gap-3 rounded-xl border border-border bg-surface-2/40 p-3 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div className="relative aspect-video w-28 shrink-0 overflow-hidden rounded-lg border border-border bg-black">
          {ready ? (
            // A real frame of the rendered clip as its thumbnail (owner-only stream).
            <video
              aria-hidden="true"
              tabIndex={-1}
              muted
              preload="metadata"
              src={`${clipContentUrl(clip.id)}#t=0.5`}
              className="size-full object-cover"
            />
          ) : (
            <span className="flex size-full items-center justify-center text-subtle">
              <Clapperboard aria-hidden="true" className="size-4" />
            </span>
          )}
        </div>
        <div className="min-w-0">
          <p className="line-clamp-2 text-sm font-medium break-words text-foreground">{clip.title}</p>
          <p className="tabular mt-1 text-xs text-subtle">
            {formatTimestamp(clip.start_time)} – {formatTimestamp(clip.end_time)} · {formatDuration(clip.duration_seconds)}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ClipStatus clip={clip} />
            {shorts && (shorts.ready > 0 || shorts.active > 0) ? (
              <span className="inline-flex items-center gap-1 text-xs text-muted">
                <Smartphone aria-hidden="true" className="size-3.5" />
                {shorts.ready} short{shorts.ready === 1 ? "" : "s"}
                {shorts.active > 0 ? ` · ${shorts.active} rendering` : ""}
              </span>
            ) : null}
          </div>
        </div>
      </div>
      {ready ? (
        <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
          <a
            href={clipDownloadUrl(clip.id)}
            download
            className={buttonClasses("secondary", "sm")}
            aria-label={`Download clip — ${clip.title}`}
          >
            <Download aria-hidden="true" />
            Download
          </a>
          {shorts && shorts.ready > 0 ? (
            <>
              <Link
                href={createHref(projectId, clip.id)}
                className={buttonClasses("secondary", "sm")}
                aria-label={`Create another Short — ${clip.title}`}
              >
                <Wand2 aria-hidden="true" />
                New Short
              </Link>
              <Link href={editorHref(projectId, clip.id)} className={buttonClasses("primary", "sm")}>
                <Smartphone aria-hidden="true" />
                Open editor
              </Link>
            </>
          ) : (
            <Link
              href={createHref(projectId, clip.id)}
              className={buttonClasses("primary", "sm")}
              aria-label={`Create Short — ${clip.title}`}
            >
              <Wand2 aria-hidden="true" />
              Create Short
            </Link>
          )}
        </div>
      ) : null}
    </li>
  );
}

/** Every rendered clip of this video and how many vertical shorts each one has. */
export function GeneratedClipsPanel({
  projectId,
  clips,
}: {
  projectId: string;
  clips: Map<string, GeneratedClip> | null;
}) {
  const ordered = useMemo(
    () => (clips ? [...clips.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)) : []),
    [clips],
  );
  const readyKey = ordered
    .filter((clip) => clip.status === "ready")
    .map((clip) => `${clip.video_id}:${clip.id}`)
    .join(",");
  const [shorts, setShorts] = useState<Map<string, ShortCounts>>(new Map());

  useEffect(() => {
    if (!readyKey) return;
    let cancelled = false;
    Promise.all(
      readyKey.split(",").map(async (pair) => {
        const [videoId, clipId] = pair.split(":");
        try {
          const page = await listEdits(projectId, videoId, clipId);
          return [
            clipId,
            {
              ready: page.edits.filter((e) => e.status === "ready").length,
              active: page.edits.filter((e) => isEditActive(e.status) && !e.is_stale).length,
            },
          ] as const;
        } catch {
          return null;
        }
      }),
    ).then((entries) => {
      if (!cancelled) setShorts(new Map(entries.filter((e) => e !== null)));
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, readyKey]);


  return (
    <Panel
      id="generated"
     
      title="Generated clips"
      description="Rendered clips from your candidates, and their vertical shorts."
    >
      {clips === null ? (
        <LoadingState label="Loading generated clips…" />
      ) : ordered.length === 0 ? (
        <EmptyState
          compact
          icon={Clapperboard}
          title="No generated clips yet"
          description="Generate a candidate to create your first clip."
        />
      ) : (
        <ul className="space-y-2">
          {ordered.map((clip) => (
            <ClipRow key={clip.id} clip={clip} shorts={shorts.get(clip.id)} projectId={projectId} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
