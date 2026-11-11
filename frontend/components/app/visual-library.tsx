"use client";

import { AssetLabelsForm } from "@/components/app/asset-labels-form";
import { CheckCircle2, CircleAlert, Film, Image as ImageIcon, Images, Loader, RotateCcw, Search, Trash2, Upload as UploadIcon, UploadCloud, X } from "lucide-react";
import { type DragEvent, type FormEvent, type ReactNode, useCallback, useId, useMemo, useRef, useState } from "react";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { inputBase, inputClasses, textareaClasses } from "@/components/ui/input-styles";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { ProgressBar, Spinner } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { batchSummary } from "@/lib/upload-batch";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";
import { useVisualSearch } from "@/components/app/use-visual-search";
import {
  bestSceneLabel,
  canSearchByContent,
  deleteVisual,
  isPreparing,
  filterVisuals,
  formatVisualDuration,
  listVisuals,
  matchReason,
  orientationLabel,
  parseTagText,
  retryVisualSearch,
  SEARCH_MAX_CHARS,
  searchNote,
  asSentence,
  searchStateLabel,
  searchText,
  splitByStrength,
  splitLocal,
  STRENGTH_LABEL,
  updateVisual,
  uploadVisual,
  VISUAL_ACCEPT,
  visualContentUrl,
  visualThumbnailUrl,
  type VisualAsset,
  type VisualFilter,
  type VisualMatch,
} from "@/lib/visuals";

type Filter = VisualFilter;
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "image", label: "Images" },
  { value: "video", label: "Videos" },
];

type Shown = { asset: VisualAsset; match?: VisualMatch; local?: boolean };
type Preview = { asset: VisualAsset; startAt: number | null };

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
    // A locally added or edited copy keeps its details; its visual-search state comes from the
    // latest load (indexing moves on in the background).
    const loaded = new Map((data ?? []).map((a) => [a.id, a]));
    return [...added, ...(data ?? [])]
      .filter((a) => !removed.has(a.id) && !seen.has(a.id) && Boolean(seen.add(a.id)))
      .map((a) => {
        const fresh = loaded.get(a.id);
        return fresh && fresh !== a ? { ...a, visual_search: fresh.visual_search } : a;
      });
  }, [added, data, removed]);
  // While any asset is still being prepared for visual search, refresh the list quietly.
  usePolling(
    assets.some((a) => isPreparing(a.visual_search?.state)),
    async () => reload(),
    projectId,
  );
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);

  const text = searchText(query);
  const search = useVisualSearch(projectId, text, filter === "all" ? null : filter, added.length + removed.size);
  const shown: Shown[] = useMemo(() => {
    if (!text) return filterVisuals(assets, filter, "").map((asset) => ({ asset }));
    if (search.error) return filterVisuals(assets, filter, text).map((asset) => ({ asset }));
    // Search answers carry the asset as the server saw it; prefer this page's latest copy.
    const latest = new Map(assets.map((a) => [a.id, a]));
    return (search.results?.results ?? [])
      .filter((hit) => latest.has(hit.asset.id))
      .map((hit) => ({ asset: latest.get(hit.asset.id) ?? hit.asset, match: hit.match, local: hit.local }));
  }, [assets, filter, text, search.results, search.error]);
  const note = text && !search.error ? searchNote(search.results) : null;

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

  const byContent = canSearchByContent(assets.map((a) => a.visual_search));
  const preparing = assets.some((a) => isPreparing(a.visual_search?.state));
  const tiers = text ? splitByStrength(shown) : { best: [], more: shown };
  // In a local market (Morocco Mode): local strong matches first, then Global ones; weaker
  // matches stay below both.
  const local = text ? splitLocal(shown) : null;
  const open = ({ asset, match }: Shown) => setPreview({ asset, startAt: match?.best_frame_time ?? null });
  const drop = useFileDrop(busy, addFiles);

  return (
    <Panel
      id="visuals"
      title="Visuals"
      description="Images and B-roll videos for cutaways and overlays. Upload only media you own or have permission to use."
      className="mt-8"
      actions={assets.length ? <UploadButton disabled={busy} onFiles={addFiles} /> : undefined}
    >
      <div {...drop.handlers} className="relative space-y-5">
        {drop.dragging && assets.length ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -inset-2 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent bg-background/85 text-sm font-medium text-foreground"
          >
            <UploadCloud className="mr-2 size-5 text-accent-soft" />
            Drop to add to this project
          </div>
        ) : null}
        {uploads.length ? (
          <UploadBatch
            uploads={uploads}
            onDismiss={() => setUploads((u) => u.filter((x) => x.state === "uploading" || x.state === "processing"))}
          />
        ) : null}

        {loading && !data ? (
          <div role="status" aria-label="Loading your visuals" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="aspect-[4/3] rounded-xl" />
            ))}
          </div>
        ) : error ? (
          <ErrorState title="Your visuals couldn't be loaded" message={error} onRetry={reload} />
        ) : assets.length === 0 ? (
          <div className="space-y-4">
            <EmptyState
              compact
              icon={Images}
              title="No visuals yet"
              description="Add images or short videos to use as B-roll in your Shorts. PeakSift can then suggest them for the right moments."
            />
            <DropZone disabled={busy} onFiles={addFiles} />
          </div>
        ) : (
          <>
            <Toolbar
              filter={filter}
              onFilter={setFilter}
              query={query}
              onQuery={setQuery}
              searching={search.searching}
              byContent={byContent}
              preparing={preparing}
            />
            {note ? <p className="text-xs text-muted">{note}</p> : null}
            {search.error ? (
              <InlineAlert title="Visual search is unavailable right now">
                Showing visuals whose name, description or tags match instead.
              </InlineAlert>
            ) : null}
            <p className="sr-only" role="status" aria-live="polite">
              {search.searching
                ? "Searching…"
                : text
                  ? `${shown.length} visual${shown.length === 1 ? "" : "s"} found`
                  : `${shown.length} of ${assets.length} visuals shown`}
            </p>
            {shown.length ? (
              <div className="space-y-5" aria-busy={search.searching}>
                {local ? (
                  <>
                    {local.local.length ? <AssetGrid title="Local matches" projectId={projectId} items={local.local} onOpen={open} /> : null}
                    {local.global.length ? <AssetGrid title="Global alternatives" projectId={projectId} items={local.global} onOpen={open} /> : null}
                  </>
                ) : tiers.best.length ? (
                  <AssetGrid title="Best matches" projectId={projectId} items={tiers.best} onOpen={open} />
                ) : null}
                {tiers.more.length ? (
                  <AssetGrid
                    title={tiers.best.length ? "More results" : undefined}
                    label={text ? "Search results" : "Visuals"}
                    projectId={projectId}
                    items={tiers.more}
                    onOpen={open}
                  />
                ) : null}
              </div>
            ) : search.searching ? (
              <p className="text-sm text-muted">Searching…</p>
            ) : (
              <p className="text-sm text-muted">
                {text ? `No visuals match “${text}”. Try other words, or clear the search.` : "No visuals match this filter."}
              </p>
            )}
          </>
        )}
      </div>
      <PreviewDialog
        key={preview?.asset.id ?? "closed"}
        projectId={projectId}
        asset={preview?.asset ?? null}
        startAt={preview?.startAt ?? null}
        onClose={() => setPreview(null)}
        onUpdated={(asset) => {
          setAdded((previous) => [asset, ...previous.filter((a) => a.id !== asset.id)]);
          setPreview((previous) => ({ asset, startAt: previous?.startAt ?? null }));
        }}
        onRetried={(asset) => {
          setAdded((previous) => [asset, ...previous.filter((a) => a.id !== asset.id)]);
          setPreview((previous) => ({ asset, startAt: previous?.startAt ?? null }));
          reload();
        }}
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

/** Accepts files dropped anywhere on the library (enter/leave are counted: children fire them too). */
function useFileDrop(disabled: boolean, onFiles: (files: FileList | null) => void) {
  const depth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const hasFiles = (event: DragEvent) => Array.from(event.dataTransfer.types).includes("Files");
  return {
    dragging,
    handlers: {
      onDragEnter: (event: DragEvent) => {
        if (!hasFiles(event) || disabled) return;
        depth.current += 1;
        setDragging(true);
      },
      onDragOver: (event: DragEvent) => {
        if (hasFiles(event)) event.preventDefault();
      },
      onDragLeave: (event: DragEvent) => {
        if (!hasFiles(event) || disabled) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setDragging(false);
      },
      onDrop: (event: DragEvent) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        depth.current = 0;
        setDragging(false);
        if (!disabled) onFiles(event.dataTransfer.files);
      },
    },
  };
}

function UploadButton({ disabled, onFiles }: { disabled: boolean; onFiles: (files: FileList | null) => void }) {
  return (
    <label
      className={`inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-border-strong bg-surface-2 px-3 text-small font-medium text-foreground transition-colors hover:bg-surface-3 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent pointer-coarse:h-11 ${
        disabled ? "pointer-events-none opacity-60" : ""
      }`}
    >
      <UploadIcon aria-hidden="true" className="size-4" />
      Upload files
      <input
        type="file"
        multiple
        accept={VISUAL_ACCEPT}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          onFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </label>
  );
}

/** One summary for everything being added: a single progress bar, then what failed and why. */
function UploadBatch({ uploads, onDismiss }: { uploads: Upload[]; onDismiss: () => void }) {
  const summary = batchSummary(uploads);
  const failures = uploads.filter((u) => u.state === "failed");
  const checking = uploads.some((u) => u.state === "processing");
  return (
    <section aria-label="Uploads" className="rounded-xl border border-border bg-surface-2 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="flex min-w-0 items-center gap-2 text-sm text-foreground" role="status">
          {summary.working ? (
            <Spinner />
          ) : summary.failed ? (
            <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-amber-300" />
          ) : (
            <CheckCircle2 aria-hidden="true" className="size-4 shrink-0 text-emerald-300" />
          )}
          <span className="min-w-0">
            {summary.label}
            {summary.working && checking ? <span className="text-muted"> · checking files and making previews</span> : null}
          </span>
        </p>
        {!summary.working ? (
          <Button variant="ghost" size="sm" className="px-2" aria-label="Dismiss upload summary" onClick={onDismiss}>
            <X aria-hidden="true" />
          </Button>
        ) : null}
      </div>
      {summary.working ? (
        <div className="mt-2.5">
          <ProgressBar value={summary.percent} label="Upload progress" />
        </div>
      ) : null}
      {failures.length ? (
        <ul className="mt-2.5 space-y-1 text-xs" aria-label="Files that couldn't be added">
          {failures.map((u) => (
            <li key={u.key} className="flex flex-wrap gap-x-2">
              <span className="max-w-full truncate font-medium text-foreground" title={u.name}>
                {u.name}
              </span>
              <span className="text-amber-200">{u.message ?? "The upload failed"}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function AssetGrid({
  title,
  label,
  projectId,
  items,
  onOpen,
}: {
  title?: string;
  label?: string;
  projectId: string;
  items: Shown[];
  onOpen: (item: Shown) => void;
}): ReactNode {
  const headingId = useId();
  return (
    <section aria-labelledby={title ? headingId : undefined} aria-label={title ? undefined : label} className="space-y-2.5">
      {title ? (
        <h3 id={headingId} className="text-small font-medium text-muted">
          {title}
        </h3>
      ) : null}
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {items.map((item) => (
          <li key={item.asset.id}>
            <AssetCard projectId={projectId} asset={item.asset} match={item.match} onOpen={() => onOpen(item)} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Toolbar({
  filter,
  onFilter,
  query,
  onQuery,
  searching,
  byContent,
  preparing,
}: {
  filter: Filter;
  onFilter: (filter: Filter) => void;
  query: string;
  onQuery: (query: string) => void;
  searching: boolean;
  /** At least one visual can be found by what it shows. */
  byContent: boolean;
  preparing: boolean;
}) {
  const searchId = useId();
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor={searchId} className="sr-only">
          Search your visuals
        </label>
        <div className="relative">
          <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-subtle" />
          <input
            id={searchId}
            type="search"
            value={query}
            maxLength={SEARCH_MAX_CHARS}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Search your visuals"
            aria-describedby={`${searchId}-hint`}
            className={`${inputBase} h-11 pr-10 pl-10 text-lead`}
          />
          {searching ? <Spinner className="absolute top-1/2 right-3.5 size-4 -translate-y-1/2" /> : null}
        </div>
        <p id={`${searchId}-hint`} className="mt-1.5 text-caption text-subtle">
          {byContent
            ? "Describe what you need, like “people talking” or “a bridge at night”. Names, descriptions and tags work too."
            : preparing
              ? "Searching names, descriptions and tags. Search by what's in a shot starts once your visuals are prepared."
              : "Search names, descriptions and tags."}
        </p>
      </div>
      <SegmentedControl label="Show" value={filter} onChange={onFilter} options={FILTERS} size="sm" />
    </div>
  );
}

function AssetCard({
  projectId,
  asset,
  match,
  onOpen,
}: {
  projectId: string;
  asset: VisualAsset;
  match?: VisualMatch;
  onOpen: () => void;
}) {
  const Icon = asset.kind === "video" ? Film : ImageIcon;
  const scene = asset.kind === "video" ? bestSceneLabel(match?.best_frame_time) : null;
  const found = match ? ` — ${STRENGTH_LABEL[match.strength]}, ${matchReason(match).toLowerCase()}${scene ? `, ${scene.toLowerCase()}` : ""}` : "";
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group block w-full overflow-hidden rounded-xl border border-border bg-surface-2 text-left transition-colors hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      aria-label={`Preview ${asset.display_name} (${asset.kind === "video" ? `video, ${formatVisualDuration(asset.duration_seconds ?? 0)}` : "image"})${found}${stateNote(asset)}`}
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
        <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 rounded-md bg-black/70 px-1.5 py-0.5 text-caption font-medium text-white">
          <Icon aria-hidden="true" className="size-3" />
          {asset.kind === "video" ? formatVisualDuration(asset.duration_seconds ?? 0) : "Image"}
        </span>
        <SearchStateMark asset={asset} />
      </span>
      <span className="block px-2.5 py-2">
        <span className="block truncate text-small font-medium text-foreground" title={asset.display_name}>
          {asset.display_name}
        </span>
        <span className="block text-caption text-subtle">
          {orientationLabel(asset)}
          {asset.has_alpha ? " · Transparent" : ""}
        </span>
        {match ? (
          <span className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1" title={matchReason(match)}>
            <span
              className={`rounded-md px-1.5 py-0.5 text-caption font-medium ${
                match.strength === "strong" ? "bg-emerald-400/15 text-emerald-200" : "bg-white/[0.07] text-muted"
              }`}
            >
              {STRENGTH_LABEL[match.strength]}
            </span>
            {scene ? <span className="text-caption text-subtle">{scene}</span> : null}
          </span>
        ) : null}
      </span>
    </button>
  );
}

/** Only "preparing" and "unavailable" are marked on a card; ready is the normal state. */
function stateNote(asset: VisualAsset): string {
  const state = asset.visual_search?.state;
  if (state === "failed") return ". Visual search unavailable";
  if (isPreparing(state)) return ". Preparing visual search";
  return "";
}

function SearchStateMark({ asset }: { asset: VisualAsset }) {
  const state = asset.visual_search?.state;
  const label = searchStateLabel(asset.visual_search);
  if (!label || state === "ready") return null;
  const failed = state === "failed";
  const Mark = failed ? CircleAlert : Loader;
  return (
    <span
      title={label}
      className={`absolute top-1.5 right-1.5 inline-flex size-5 items-center justify-center rounded-md bg-black/70 ${failed ? "text-amber-300" : "text-white/80"}`}
    >
      <Mark aria-hidden="true" className={`size-3 ${failed ? "" : "motion-safe:animate-spin"}`} />
    </span>
  );
}

function VisualSearchDetails({ projectId, asset, onRetried }: { projectId: string; asset: VisualAsset; onRetried: (asset: VisualAsset) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = asset.visual_search;
  const label = searchStateLabel(status);
  if (!status || !label) return null;
  async function retry() {
    setBusy(true);
    setError(null);
    try {
      onRetried(await retryVisualSearch(projectId, asset.id));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border px-3 py-2">
      <div className="min-w-0">
        <p className="text-small font-medium text-foreground" role="status">
          {label}
        </p>
        <p className="text-xs text-muted">
          {status.state === "ready"
            ? "This visual can be found by what it shows."
            : status.state === "failed"
              ? `${asSentence(status.message ?? "It could not be analysed")} You can still use it by hand.`
              : "It can already be used by hand; search by what it shows follows shortly."}
        </p>
        {error ? <p className="mt-1 text-xs text-amber-300">{error}</p> : null}
      </div>
      {status.state === "failed" && status.can_retry ? (
        <Button size="sm" variant="secondary" onClick={retry} disabled={busy}>
          <RotateCcw aria-hidden="true" />
          {busy ? "Starting…" : "Retry visual analysis"}
        </Button>
      ) : null}
    </div>
  );
}

function PreviewDialog({
  projectId,
  asset,
  startAt,
  onClose,
  onUpdated,
  onRetried,
  onDeleted,
}: {
  projectId: string;
  asset: VisualAsset | null;
  /** Videos opened from a search result start at the scene that matched. */
  startAt: number | null;
  onClose: () => void;
  onUpdated: (asset: VisualAsset) => void;
  onRetried: (asset: VisualAsset) => void;
  onDeleted: (id: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();


  async function remove() {
    if (!asset) return;
    setBusy(true);
    setError(null);
    try {
      await deleteVisual(projectId, asset.id);
      onDeleted(asset.id);
      toast("Visual deleted");
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <Dialog
      open={!!asset}
      onClose={onClose}
      width="44rem"
      title={asset?.display_name ?? "Visual"}
      description={
        asset ? (
          <>
            {asset.kind === "video" ? `Video · ${formatVisualDuration(asset.duration_seconds ?? 0)}` : "Image"} ·{" "}
            {asset.width} × {asset.height} · {formatBytes(asset.file_size)}
            {asset.kind === "video" && asset.has_audio ? " · Sound is not used" : ""}
          </>
        ) : undefined
      }
    >
      {asset ? (
          <div className="space-y-4">
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
                  onLoadedMetadata={(event) => {
                    const video = event.currentTarget;
                    if (startAt != null && Number.isFinite(video.duration)) {
                      video.currentTime = Math.min(Math.max(0, startAt), video.duration);
                    }
                  }}
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
            {asset.kind === "video" && startAt != null ? (
              <p className="text-xs text-muted">Opened at the scene that matched your search ({bestSceneLabel(startAt)?.replace("Best at ", "")}).</p>
            ) : null}
            <VisualSearchDetails projectId={projectId} asset={asset} onRetried={onRetried} />
            <DetailsForm projectId={projectId} asset={asset} onUpdated={onUpdated} />
            <AssetLabelsForm
              family="visual"
              asset={asset}
              onSave={async (changes) => onUpdated(await updateVisual(projectId, asset.id, changes))}
            />
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
            </div>
          </div>
      ) : null}
    </Dialog>
  );
}

function DetailsForm({
  projectId,
  asset,
  onUpdated,
}: {
  projectId: string;
  asset: VisualAsset;
  onUpdated: (asset: VisualAsset) => void;
}) {
  const id = useId();
  const [name, setName] = useState(asset.display_name);
  const [description, setDescription] = useState(asset.description);
  const [tags, setTags] = useState(asset.tags.join(", "));
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const changed = name !== asset.display_name || description !== asset.description || tags !== asset.tags.join(", ");

  async function save(event: FormEvent) {
    event.preventDefault();
    setState("saving");
    setError(null);
    try {
      const updated = await updateVisual(projectId, asset.id, {
        display_name: name,
        description,
        tags: parseTagText(tags),
      });
      setTags(updated.tags.join(", "));
      setState("saved");
      onUpdated(updated);
    } catch (failure) {
      setError(errorMessage(failure));
      setState("idle");
    }
  }

  return (
    <form onSubmit={save} className="space-y-3 rounded-xl border border-border p-3">
      <p className="text-small font-medium text-foreground">Details</p>
      <p className="text-xs text-muted">A description and tags help match B-roll suggestions to this asset.</p>
      <div className="space-y-1">
        <label htmlFor={`${id}-name`} className="text-xs font-medium text-muted">Name</label>
        <input id={`${id}-name`} value={name} maxLength={255} onChange={(e) => { setName(e.target.value); setState("idle"); }} className={inputClasses} />
      </div>
      <div className="space-y-1">
        <label htmlFor={`${id}-description`} className="text-xs font-medium text-muted">Description</label>
        <textarea id={`${id}-description`} value={description} maxLength={500} rows={2} onChange={(e) => { setDescription(e.target.value); setState("idle"); }} className={textareaClasses} />
      </div>
      <div className="space-y-1">
        <label htmlFor={`${id}-tags`} className="text-xs font-medium text-muted">Tags <span className="font-normal">(comma-separated)</span></label>
        <input id={`${id}-tags`} value={tags} onChange={(e) => { setTags(e.target.value); setState("idle"); }} placeholder="rocket, space, launch" className={inputClasses} />
      </div>
      {error ? <InlineAlert title="The details could not be saved">{error}</InlineAlert> : null}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" variant="secondary" disabled={!changed || state === "saving"}>
          {state === "saving" ? "Saving…" : "Save details"}
        </Button>
        {state === "saved" && !changed ? <span role="status" className="text-xs text-emerald-300">Saved</span> : null}
      </div>
    </form>
  );
}
