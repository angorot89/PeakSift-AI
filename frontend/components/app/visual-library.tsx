"use client";

import { CheckCircle2, Film, Image as ImageIcon, Images, Search, Trash2, UploadCloud, X } from "lucide-react";
import { type DragEvent, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { ProgressBar, Spinner } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import {
  deleteVisual,
  filterVisuals,
  formatVisualDuration,
  listVisuals,
  orientationLabel,
  uploadVisual,
  VISUAL_ACCEPT,
  visualContentUrl,
  visualThumbnailUrl,
  type VisualAsset,
  type VisualFilter,
} from "@/lib/visuals";

type Filter = VisualFilter;
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "image", label: "Images" },
  { value: "video", label: "Videos" },
];

type Upload = {
  key: string;
  name: string;
  size: number;
  state: "uploading" | "processing" | "done" | "existing" | "failed";
  progress: number;
  message?: string;
};

/** The project's private images and B-roll videos: upload, browse, search, preview. */
export function VisualLibrary({ projectId }: { projectId: string }) {
  const load = useCallback(() => listVisuals(projectId), [projectId]);
  const { data, error, loading, reload } = useApi(load);
  // Uploads and deletions apply locally on top of the loaded list (no reload needed).
  const [added, setAdded] = useState<VisualAsset[]>([]);
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const assets = useMemo(() => {
    const seen = new Set<string>();
    return [...added, ...(data ?? [])].filter((a) => !removed.has(a.id) && !seen.has(a.id) && Boolean(seen.add(a.id)));
  }, [added, data, removed]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [preview, setPreview] = useState<VisualAsset | null>(null);

  const shown = useMemo(() => filterVisuals(assets, filter, query), [assets, filter, query]);

  const busy = uploads.some((u) => u.state === "uploading" || u.state === "processing");

  async function addFiles(files: FileList | File[] | null) {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    const queued = list.map((file, index) => ({
      key: `${Date.now()}-${index}-${file.name}`,
      name: file.name,
      size: file.size,
      state: "uploading" as const,
      progress: 0,
    }));
    setUploads((previous) => [...queued, ...previous.filter((u) => u.state !== "done" && u.state !== "existing")]);
    const update = (key: string, patch: Partial<Upload>) =>
      setUploads((previous) => previous.map((u) => (u.key === key ? { ...u, ...patch } : u)));
    for (const [index, file] of list.entries()) {
      const { key } = queued[index];
      try {
        const { asset, existing } = await uploadVisual(projectId, file, (percent) =>
          update(key, percent >= 100 ? { progress: 100, state: "processing" } : { progress: percent }),
        );
        update(key, { state: existing ? "existing" : "done", progress: 100 });
        setAdded((previous) => [asset, ...previous.filter((a) => a.id !== asset.id)]);
        setRemoved((previous) => {
          if (!previous.has(asset.id)) return previous;
          const next = new Set(previous);
          next.delete(asset.id);
          return next;
        });
      } catch (failure) {
        update(key, { state: "failed", message: errorMessage(failure) });
      }
    }
  }

  return (
    <Panel
      id="visuals"
      title="Visual assets"
      description="Images and B-roll videos for cutaways and overlays. Upload only media you own or have permission to use."
      className="mt-8"
    >
      <div className="space-y-5">
        <DropZone disabled={busy} onFiles={addFiles} />
        {uploads.length ? <UploadList uploads={uploads} onDismiss={(key) => setUploads((u) => u.filter((x) => x.key !== key))} /> : null}

        {loading && !data ? (
          <LoadingState label="Loading visual assets…" />
        ) : error ? (
          <ErrorState title="Visual assets could not be loaded" message={error} onRetry={reload} />
        ) : assets.length === 0 ? (
          <EmptyState
            compact
            icon={Images}
            title="No visual assets yet"
            description="Add images or short videos to use as B-roll in your shorts."
          />
        ) : (
          <>
            <Toolbar filter={filter} onFilter={setFilter} query={query} onQuery={setQuery} />
            <p className="sr-only" role="status" aria-live="polite">
              {shown.length} of {assets.length} visual assets shown
            </p>
            {shown.length ? (
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label="Visual assets">
                {shown.map((asset) => (
                  <li key={asset.id}>
                    <AssetCard projectId={projectId} asset={asset} onOpen={() => setPreview(asset)} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No visual assets match these filters.</p>
            )}
          </>
        )}
      </div>
      <PreviewDialog
        key={preview?.id ?? "closed"}
        projectId={projectId}
        asset={preview}
        onClose={() => setPreview(null)}
        onDeleted={(id) => {
          setRemoved((previous) => new Set(previous).add(id));
          setPreview(null);
        }}
      />
    </Panel>
  );
}

function DropZone({ disabled, onFiles }: { disabled: boolean; onFiles: (files: FileList | null) => void }) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);
  function drop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) onFiles(event.dataTransfer.files);
  }
  return (
    <label
      htmlFor={inputId}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
      className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed px-4 py-6 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
        dragging ? "border-accent bg-accent/5" : "border-border-strong hover:border-white/30 hover:bg-surface-2/50"
      } ${disabled ? "pointer-events-none opacity-60" : ""}`}
    >
      <input
        id={inputId}
        type="file"
        multiple
        accept={VISUAL_ACCEPT}
        disabled={disabled}
        className="sr-only"
        aria-describedby={`${inputId}-hint`}
        onChange={(event) => {
          onFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <UploadCloud aria-hidden="true" className="size-5 text-accent-soft" />
      <span className="text-sm font-medium text-foreground">
        Drop images or videos here, or <span className="text-accent-soft underline underline-offset-2">browse</span>
      </span>
      <span id={`${inputId}-hint`} className="text-xs text-muted">
        JPEG, PNG or WebP images; MP4, MOV or WebM videos. Video sound is not used.
      </span>
    </label>
  );
}

function UploadList({ uploads, onDismiss }: { uploads: Upload[]; onDismiss: (key: string) => void }) {
  return (
    <ul className="space-y-2" aria-label="Uploads">
      {uploads.map((u) => (
        <li key={u.key} className="rounded-lg border border-border bg-surface-2 px-3 py-2.5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground" title={u.name}>
                {u.name} <span className="font-normal text-subtle">· {formatBytes(u.size)}</span>
              </p>
              <p className="text-xs text-muted" role={u.state === "failed" ? "alert" : "status"}>
                {u.state === "uploading" && `Uploading · ${u.progress}%`}
                {u.state === "processing" && "Checking the file and making a preview…"}
                {u.state === "done" && "Added"}
                {u.state === "existing" && "Already in this project"}
                {u.state === "failed" && (u.message ?? "The upload failed")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {u.state === "processing" ? <Spinner /> : null}
              {u.state === "done" || u.state === "existing" ? (
                <CheckCircle2 aria-hidden="true" className="size-4 text-emerald-300" />
              ) : null}
              {u.state === "failed" || u.state === "done" || u.state === "existing" ? (
                <Button variant="ghost" size="sm" className="px-2" aria-label={`Dismiss ${u.name}`} onClick={() => onDismiss(u.key)}>
                  <X aria-hidden="true" />
                </Button>
              ) : null}
            </div>
          </div>
          {u.state === "uploading" ? (
            <div className="mt-2">
              <ProgressBar value={u.progress} label={`Upload progress for ${u.name}`} />
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function Toolbar({
  filter,
  onFilter,
  query,
  onQuery,
}: {
  filter: Filter;
  onFilter: (filter: Filter) => void;
  query: string;
  onQuery: (query: string) => void;
}) {
  const searchId = useId();
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div role="group" aria-label="Show" className="inline-flex w-fit rounded-lg border border-border bg-surface-2 p-0.5">
        {FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={filter === option.value}
            onClick={() => onFilter(option.value)}
            className={`h-8 rounded-md px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
              filter === option.value ? "bg-surface-3 text-foreground" : "text-muted hover:text-foreground"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="relative w-full sm:w-64">
        <label htmlFor={searchId} className="sr-only">
          Search visual assets by name
        </label>
        <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
        <input
          id={searchId}
          type="search"
          value={query}
          maxLength={100}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search by name"
          className="h-9 w-full rounded-lg border border-border bg-white/[0.03] pr-3 pl-9 text-sm text-foreground outline-none placeholder:text-subtle focus:border-accent/60 focus-visible:ring-2 focus-visible:ring-accent/40"
        />
      </div>
    </div>
  );
}

function AssetCard({ projectId, asset, onOpen }: { projectId: string; asset: VisualAsset; onOpen: () => void }) {
  const Icon = asset.kind === "video" ? Film : ImageIcon;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group block w-full overflow-hidden rounded-xl border border-border bg-surface-2 text-left transition-colors hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      aria-label={`Preview ${asset.display_name} (${asset.kind === "video" ? `video, ${formatVisualDuration(asset.duration_seconds ?? 0)}` : "image"})`}
    >
      <span className={`relative flex aspect-video items-center justify-center overflow-hidden ${asset.has_alpha ? "checkerboard" : "bg-black"}`}>
        {asset.has_thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element -- private, authenticated API image
          <img
            src={visualThumbnailUrl(projectId, asset.id)}
            alt=""
            loading="lazy"
            className="size-full object-contain"
          />
        ) : (
          <Icon aria-hidden="true" className="size-6 text-subtle" />
        )}
        <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-white">
          <Icon aria-hidden="true" className="size-3" />
          {asset.kind === "video" ? formatVisualDuration(asset.duration_seconds ?? 0) : "Image"}
        </span>
      </span>
      <span className="block px-2.5 py-2">
        <span className="block truncate text-[13px] font-medium text-foreground" title={asset.display_name}>
          {asset.display_name}
        </span>
        <span className="block text-[11px] text-subtle">
          {orientationLabel(asset)}
          {asset.has_alpha ? " · Transparent" : ""}
        </span>
      </span>
    </button>
  );
}

function PreviewDialog({
  projectId,
  asset,
  onClose,
  onDeleted,
}: {
  projectId: string;
  asset: VisualAsset | null;
  onClose: () => void;
  onDeleted: (id: string) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (asset && !dialog.open) dialog.showModal();
    if (!asset && dialog.open) dialog.close();
  }, [asset]);

  async function remove() {
    if (!asset) return;
    setBusy(true);
    setError(null);
    try {
      await deleteVisual(projectId, asset.id);
      onDeleted(asset.id);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby={titleId}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(44rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-border bg-surface p-0 text-foreground shadow-2xl backdrop:bg-black/70"
    >
      {asset ? (
        <>
          <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-4 sm:px-6">
            <div className="min-w-0">
              <h2 id={titleId} className="truncate text-[15px] font-semibold tracking-tight" title={asset.display_name}>
                {asset.display_name}
              </h2>
              <p className="mt-0.5 text-sm text-muted">
                {asset.kind === "video" ? `Video · ${formatVisualDuration(asset.duration_seconds ?? 0)}` : "Image"} ·{" "}
                {asset.width} × {asset.height} · {formatBytes(asset.file_size)}
                {asset.kind === "video" && asset.has_audio ? " · Sound is not used" : ""}
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => ref.current?.close()} aria-label="Close" className="px-2">
              <X aria-hidden="true" />
            </Button>
          </div>
          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className={`flex max-h-[60dvh] items-center justify-center overflow-hidden rounded-xl ${asset.has_alpha ? "checkerboard" : "bg-black"}`}>
              {asset.kind === "video" ? (
                <video
                  key={asset.id}
                  src={visualContentUrl(projectId, asset.id)}
                  controls
                  muted
                  playsInline
                  preload="metadata"
                  className="max-h-[60dvh] w-full object-contain"
                  aria-label={`Preview of ${asset.display_name}`}
                />
              ) : (
                // eslint-disable-next-line @next/next/no-img-element -- private, authenticated API image
                <img
                  src={visualContentUrl(projectId, asset.id)}
                  alt={`Preview of ${asset.display_name}`}
                  className="max-h-[60dvh] w-auto object-contain"
                />
              )}
            </div>
            {error ? <InlineAlert title="This visual could not be deleted">{error}</InlineAlert> : null}
            <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
              {confirming ? (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted">Delete this visual permanently?</span>
                  <Button variant="danger" size="sm" onClick={remove} disabled={busy}>
                    {busy ? "Deleting…" : "Delete"}
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setConfirming(false)} disabled={busy}>
                    Keep it
                  </Button>
                </div>
              ) : (
                <Button variant="secondary" size="sm" onClick={() => setConfirming(true)}>
                  <Trash2 aria-hidden="true" />
                  Delete
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => ref.current?.close()}>
                Close
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </dialog>
  );
}
