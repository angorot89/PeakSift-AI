"use client";

import { Film, Image as ImageIcon, Search, Upload } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { inputBase } from "@/components/ui/input-styles";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ProgressBar } from "@/components/ui/progress";
import { useVisualSearch } from "@/components/app/use-visual-search";
import { errorMessage } from "@/lib/api";
import type { BrollMatch } from "@/lib/broll";
import {
  bestSceneLabel,
  filterVisuals,
  formatVisualDuration,
  matchReason,
  orientationLabel,
  SEARCH_MAX_CHARS,
  searchNote,
  splitByStrength,
  searchText,
  STRENGTH_LABEL,
  uploadVisual,
  VISUAL_ACCEPT,
  visualThumbnailUrl,
  type VisualAsset,
  type VisualFilter,
  type VisualMatch,
} from "@/lib/visuals";

/** Pick one of the project's visual assets (or upload one) for a visual element. */
export function AssetChooser({
  projectId,
  open,
  title,
  assets,
  query,
  matches = [],
  initialFilter = "all",
  hint = null,
  onPick,
  onUploaded,
  onClose,
}: {
  projectId: string;
  open: boolean;
  title: string;
  assets: VisualAsset[] | null;
  /** The suggestion being matched, if any: the search starts with its words (clearable). */
  query: string | null;
  /** The suggestion's offered assets with their tier, strongest first. */
  matches?: { asset: VisualAsset; match: BrollMatch }[];
  /** Where the filter starts (the panel remounts the chooser on every open, so nothing from a
   * previous open carries over). */
  initialFilter?: VisualFilter;
  hint?: string | null;
  /** ``scene``: a video found by what it shows starts at its matched scene. */
  onPick: (asset: VisualAsset, scene?: number | null) => void;
  onUploaded: (asset: VisualAsset) => void;
  onClose: () => void;
}) {
  const searchId = useId();
  const [filter, setFilter] = useState<VisualFilter>(initialFilter);
  const [search, setSearch] = useState(query ?? "");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const text = searchText(search);
  const found = useVisualSearch(projectId, open ? text : "", filter === "all" ? null : filter, assets?.length ?? 0);
  const shown: { asset: VisualAsset; match?: VisualMatch }[] = useMemo(() => {
    const all = assets ?? [];
    if (!text) return filterVisuals(all, filter, "").map((asset) => ({ asset }));
    if (found.error) return filterVisuals(all, filter, text).map((asset) => ({ asset }));
    const latest = new Map(all.map((a) => [a.id, a]));
    return (found.results?.results ?? [])
      .filter((hit) => latest.has(hit.asset.id))
      .map((hit) => ({ asset: latest.get(hit.asset.id) ?? hit.asset, match: hit.match }));
  }, [assets, filter, text, found.results, found.error]);
  const note = text && !found.error ? searchNote(found.results) : null;
  // The suggestion's matches come first, then the rest; a search is split the same way by tier.
  const suggested = matches.length > 0 && !text;
  const suggestedIds = new Set(matches.map((m) => m.asset.id));
  const tiers = text ? splitByStrength(shown) : { best: [], more: suggested ? shown.filter((s) => !suggestedIds.has(s.asset.id)) : shown };

  async function upload(file: File | undefined) {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      const { asset } = await uploadVisual(projectId, file, setProgress);
      onUploaded(asset);
      onPick(asset);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setProgress(null);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      width="40rem"
      description={
        <>
          {query ? "Pick something that shows this, or upload it." : "From this project's visual assets."}
          {hint ? <span className="mt-1 block text-xs text-subtle">{hint}</span> : null}
        </>
      }
    >
          <div className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <SegmentedControl
                label="Show"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: "all", label: "All" },
                  { value: "image", label: "Images" },
                  { value: "video", label: "Videos" },
                ]}
              />
              <div className="w-full sm:w-64">
                <label htmlFor={searchId} className="sr-only">
                  Search your visuals
                </label>
                <div className="relative">
                  <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
                  <input
                    id={searchId}
                    type="search"
                    value={search}
                    maxLength={SEARCH_MAX_CHARS}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search your visuals"
                    aria-describedby={`${searchId}-hint`}
                    className={`${inputBase} h-10 pr-3 pl-9 text-sm pointer-coarse:h-11`}
                  />
                </div>
                <p id={`${searchId}-hint`} className="mt-1 text-caption text-subtle">
                  Search by what&apos;s in the image or video.
                </p>
              </div>
            </div>
            {note ? <p className="text-xs text-muted">{note}</p> : null}
            {found.error ? <p className="text-xs text-muted">Visual search is unavailable right now; showing name matches.</p> : null}

            {suggested || tiers.best.length ? (
              <div className="space-y-2">
                <p className="text-caption font-medium text-muted">Best matches</p>
                <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3" aria-label="Best matches">
                  {(suggested ? matches : tiers.best).map(({ asset, match }) => (
                    <li key={asset.id}>
                      <AssetButton projectId={projectId} asset={asset} match={match} onPick={() => onPick(asset, match?.best_frame_time ?? null)} />
                    </li>
                  ))}
                </ul>
                {tiers.more.length ? <p className="pt-1 text-caption font-medium text-muted">More results</p> : null}
              </div>
            ) : null}
            <p className="sr-only" role="status" aria-live="polite">
              {found.searching ? "Searching…" : text ? `${shown.length} visual${shown.length === 1 ? "" : "s"} found` : ""}
            </p>
            {assets === null ? (
              <p className="text-sm text-muted">Loading visual assets…</p>
            ) : tiers.more.length ? (
              <ul
                className="grid grid-cols-2 gap-2.5 sm:grid-cols-3"
                aria-label={suggested || tiers.best.length ? "More results" : text ? "Search results" : "Visuals"}
                aria-busy={found.searching}
              >
                {tiers.more.map(({ asset, match }) => (
                  <li key={asset.id}>
                    <AssetButton projectId={projectId} asset={asset} match={match} onPick={() => onPick(asset, match?.best_frame_time ?? null)} />
                  </li>
                ))}
              </ul>
            ) : shown.length || suggested ? null : found.searching ? (
              <p className="text-sm text-muted">Searching…</p>
            ) : (
              <p className="text-sm text-muted">
                {!assets.length
                  ? "This project has no visual assets yet. Upload one below."
                  : text
                    ? `No visuals match “${text}”. Clear the search to see them all.`
                    : "No visual assets match these filters."}
              </p>
            )}

            <div className="space-y-2 border-t border-border pt-4">
              <label
                className={`inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-control border border-border-strong bg-surface-2 px-3 text-small font-medium text-foreground transition-colors hover:bg-surface-3 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
                  progress !== null ? "pointer-events-none opacity-60" : ""
                }`}
              >
                <Upload aria-hidden="true" className="size-3.5" />
                {progress !== null ? "Uploading…" : "Upload an image or video"}
                <input
                  type="file"
                  accept={VISUAL_ACCEPT}
                  className="sr-only"
                  disabled={progress !== null}
                  onChange={(event) => {
                    void upload(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
              </label>
              <p className="text-caption text-subtle">Only media you own or have permission to use. Video sound is not used.</p>
              {progress !== null ? <ProgressBar value={progress} label="Upload progress" /> : null}
              {error ? <InlineAlert title="That file couldn't be added">{error}</InlineAlert> : null}
            </div>
          </div>
    </Dialog>
  );
}

export function AssetButton({
  projectId,
  asset,
  match,
  onPick,
}: {
  projectId: string;
  asset: VisualAsset;
  match?: Pick<VisualMatch, "strength" | "method" | "best_frame_time">;
  onPick: () => void;
}) {
  const Icon = asset.kind === "video" ? Film : ImageIcon;
  const scene = asset.kind === "video" ? bestSceneLabel(match?.best_frame_time) : null;
  const found = match ? `, ${STRENGTH_LABEL[match.strength].toLowerCase()}, ${matchReason(match).toLowerCase()}${scene ? `, ${scene.toLowerCase()}` : ""}` : "";
  return (
    <button
      type="button"
      onClick={onPick}
      aria-label={`Use ${asset.display_name} (${asset.kind === "video" ? `video, ${formatVisualDuration(asset.duration_seconds ?? 0)}` : "image"}${found})`}
      className="block w-full overflow-hidden rounded-control border border-border bg-surface-2 text-left transition-colors hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <span className={`relative flex aspect-video items-center justify-center ${asset.has_alpha ? "checkerboard" : "bg-black"}`}>
        {asset.has_thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element -- private, authenticated API image
          <img src={visualThumbnailUrl(projectId, asset.id)} alt="" loading="lazy" className="size-full object-contain" />
        ) : (
          <Icon aria-hidden="true" className="size-5 text-subtle" />
        )}
        <span className="absolute top-1 left-1 inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
          <Icon aria-hidden="true" className="size-3" />
          {asset.kind === "video" ? formatVisualDuration(asset.duration_seconds ?? 0) : "Image"}
        </span>
      </span>
      <span className="block px-2 py-1.5">
        <span className="block truncate text-caption font-medium text-foreground" title={asset.display_name}>
          {asset.display_name}
        </span>
        <span className="block text-[10px] text-subtle">{orientationLabel(asset)}</span>
        {match ? (
          <span className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5" title={matchReason(match)}>
            <span
              className={`rounded px-1 py-px text-[10px] font-medium ${
                match.strength === "strong" ? "bg-emerald-400/15 text-emerald-200" : "bg-white/[0.07] text-muted"
              }`}
            >
              {STRENGTH_LABEL[match.strength]}
            </span>
            {scene ? <span className="text-[10px] text-subtle">{scene}</span> : null}
          </span>
        ) : null}
      </span>
    </button>
  );
}
