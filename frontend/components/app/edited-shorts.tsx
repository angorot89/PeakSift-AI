"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { ShortFormEditor } from "@/components/app/short-form-editor";
import { Button } from "@/components/ui/button";
import { buttonClasses } from "@/components/ui/button-styles";
import { ApiError, errorMessage } from "@/lib/api";
import type { GeneratedClip } from "@/lib/clips";
import {
  createEdit,
  describeEdit,
  editContentUrl,
  editDownloadUrl,
  editStageLabel,
  getEdit,
  isEditActive,
  listEdits,
  retryEdit,
  type ClipEdit,
  type EditRequest,
} from "@/lib/edits";
import { formatBytes, formatDuration } from "@/lib/format";

const POLL_INTERVAL_MS = 4000;

function useSessionErrors() {
  const { setUser } = useAuth();
  return useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );
}

/**
 * Vertical shorts made from one ready clip: the edit settings, then every rendered (or
 * rendering) variant. Each variant is a separate file; the clip itself is never modified.
 */
export function ShortFormSection({ projectId, clip }: { projectId: string; clip: GeneratedClip }) {
  const handleError = useSessionErrors();
  const [edits, setEdits] = useState<ClipEdit[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listEdits(projectId, clip.video_id, clip.id)
      .then((page) => !cancelled && setEdits(page.edits))
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(handleError(err));
        setEdits([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, clip.video_id, clip.id, handleError]);

  const upsert = useCallback((edit: ClipEdit) => {
    setEdits((current) => {
      const list = current ?? [];
      // A known variant is updated in place; a new one goes to the top (newest first).
      return list.some((e) => e.id === edit.id) ? list.map((e) => (e.id === edit.id ? edit : e)) : [edit, ...list];
    });
  }, []);

  async function submit(request: EditRequest) {
    try {
      const known = edits?.some((e) => sameSettings(e, request)) ?? false;
      const edit = await createEdit(projectId, clip.video_id, clip.id, request);
      upsert(edit);
      setNotice(
        known || edit.status === "ready"
          ? `${describeEdit(edit)} already exists — shown below.`
          : `Started: ${describeEdit(edit)}.`,
      );
      return edit;
    } catch (err) {
      setNotice(null);
      throw new Error(handleError(err));
    }
  }

  const headingId = `shorts-${clip.id}`;
  return (
    <section aria-labelledby={headingId} className="space-y-4 border-t border-border pt-4">
      <h4 id={headingId} className="text-sm font-medium text-foreground">
        Make a vertical short
      </h4>
      <ShortFormEditor
        onSubmit={submit}
        footer={
          <p role="status" aria-live="polite" className="text-sm text-muted">
            {notice}
          </p>
        }
      />
      <div className="space-y-3">
        <p className="text-xs font-medium tracking-wide text-muted uppercase">
          Rendered shorts{edits && edits.length > 0 ? ` · ${edits.length}` : ""}
        </p>
        {edits === null ? (
          <p className="text-sm text-muted">Loading shorts…</p>
        ) : edits.length === 0 ? (
          <p className="text-sm text-muted">
            {loadError ?? "No shorts yet. Choose settings above and render one."}
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {edits.map((edit) => (
              <li key={edit.id} className="min-w-0">
                <EditCard projectId={projectId} clip={clip} edit={edit} onChange={upsert} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function sameSettings(edit: ClipEdit, request: EditRequest) {
  return (
    edit.layout === request.layout &&
    edit.captions_enabled === request.captions_enabled &&
    (!request.captions_enabled ||
      (edit.caption_style === request.caption_style && edit.caption_position === request.caption_position))
  );
}

type CardProps = {
  projectId: string;
  clip: GeneratedClip;
  edit: ClipEdit;
  onChange: (edit: ClipEdit) => void;
};

/** One variant: live status while it renders, then the 9:16 player and its download. */
function EditCard({ projectId, clip, edit, onChange }: CardProps) {
  const handleError = useSessionErrors();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const label = describeEdit(edit);
  const stalled = isEditActive(edit.status) && edit.is_stale;
  const polling = isEditActive(edit.status) && !edit.is_stale;

  // Poll only this variant, only while it is rendering; cleared when it settles or unmounts.
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => {
      getEdit(projectId, clip.video_id, clip.id, edit.id)
        .then(onChange)
        .catch((err: unknown) => setError(handleError(err)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [polling, projectId, clip.video_id, clip.id, edit.id, onChange, handleError]);

  async function retry() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onChange(await retryEdit(projectId, clip.video_id, clip.id, edit.id));
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  let body;
  if (edit.status === "ready") {
    body = <RenderedShort edit={edit} label={label} />;
  } else if (edit.status === "failed" || stalled) {
    body = (
      <div className="space-y-3">
        <div role="alert" className="text-sm text-rose-200">
          <p className="font-medium">{stalled ? "Render stalled — the worker stopped reporting" : "Render failed"}</p>
          {!stalled && edit.error_message ? <p className="mt-0.5 break-words">{edit.error_message}</p> : null}
        </div>
        <Button variant="secondary" onClick={retry} disabled={busy}>
          {busy ? "Retrying…" : "Retry render"}
        </Button>
      </div>
    );
  } else {
    body = (
      <div className="space-y-2">
        <p className="flex items-center gap-3 text-sm text-muted" role="status" aria-live="polite">
          <span
            aria-hidden="true"
            className="size-4 animate-spin rounded-full border-2 border-white/15 border-t-accent"
          />
          {editStageLabel(edit)}
          {edit.progress_percent > 0 ? ` — ${edit.progress_percent}%` : ""}
        </p>
        {edit.progress_percent > 0 ? (
          <div
            role="progressbar"
            aria-label={`Render progress: ${label}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={edit.progress_percent}
            className="h-1.5 overflow-hidden rounded-full bg-white/10"
          >
            <div className="h-full bg-accent transition-[width]" style={{ width: `${edit.progress_percent}%` }} />
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <article aria-label={`Short: ${label}`} className="space-y-3 rounded-lg border border-border p-3">
      <p className="text-sm font-medium break-words text-foreground">{label}</p>
      {body}
      {error ? (
        <p role="alert" className="text-sm text-rose-300">
          {error}
        </p>
      ) : null}
    </article>
  );
}

function captionFacts(edit: ClipEdit) {
  if (!edit.captions_enabled) return "No captions";
  if (edit.caption_cue_count === 0) return "No speech in this clip — rendered without captions";
  return edit.caption_cue_count != null ? `${edit.caption_cue_count} caption cues` : null;
}

/** The actual edited output: native player on the private stream and its download. */
function RenderedShort({ edit, label }: { edit: ClipEdit; label: string }) {
  const facts = [
    edit.duration_seconds != null ? formatDuration(edit.duration_seconds) : null,
    edit.width && edit.height ? `${edit.width} × ${edit.height}` : null,
    edit.file_size != null ? formatBytes(edit.file_size) : null,
    captionFacts(edit),
  ].filter(Boolean);
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        <span className="text-emerald-300">Ready</span> · {facts.join(" · ")}
      </p>
      {/* The browser sends the HttpOnly session cookie (same-site); the API checks ownership
          on every byte-range request. This is the rendered file, not a preview. */}
      <video
        controls
        playsInline
        preload="metadata"
        src={editContentUrl(edit.id)}
        className="mx-auto aspect-[9/16] w-full max-w-[260px] rounded-lg bg-black object-contain"
        aria-label={`Rendered short: ${label}`}
      />
      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted">MP4 · H.264{edit.audio_codec ? " + AAC" : " · no audio"} · 9:16</p>
        <a
          href={editDownloadUrl(edit.id)}
          className={buttonClasses("primary", "md", "w-full")}
          aria-label={`Download MP4 — ${label}`}
          download
        >
          Download MP4
        </a>
      </div>
    </div>
  );
}
