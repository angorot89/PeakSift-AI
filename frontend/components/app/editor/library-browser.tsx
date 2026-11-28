"use client";

import { Check, Library as LibraryIcon, Loader2, Pause, Play, Plus, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { errorMessage } from "@/lib/api";
import { addLibraryItem, getLibrary, libraryContentUrl, type Library, type LibraryImport, type LibraryKind } from "@/lib/library";
import { categoriesOf, categoryLabel, filterLibrary, lengthLabel } from "@/lib/library-rules";

const KIND_LABELS: Record<LibraryKind, string> = {
  sfx: "Sound effects",
  music: "Music",
  sticker: "Stickers",
  overlay: "Animated",
};

/**
 * PeakSift's built-in starter library inside an editor panel: browse, listen or look, then add
 * an item — it is imported into the project like an upload (and labelled with its licence),
 * so everything after that is the editor's usual path. Free to use in published videos.
 */
export function LibraryBrowser({
  projectId,
  kinds,
  onAdded,
}: {
  projectId: string;
  kinds: LibraryKind[];
  onAdded: (result: LibraryImport) => void;
}) {
  const id = useId();
  const [library, setLibrary] = useState<Library | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [kind, setKind] = useState<LibraryKind>(kinds[0]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [credits, setCredits] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLibrary()
      .then((data) => !cancelled && setLibrary(data))
      .catch((err: unknown) => !cancelled && setLoadError(errorMessage(err)));
    return () => {
      cancelled = true;
      audio.current?.pause();
    };
  }, []);

  const shown = useMemo(
    () => (library ? filterLibrary(library.items, kind, query, category) : []),
    [library, kind, query, category],
  );
  const categories = useMemo(() => (library ? categoriesOf(library.items, kind) : []), [library, kind]);

  function listen(itemId: string) {
    if (playing === itemId) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    const player = new Audio(libraryContentUrl(itemId));
    player.addEventListener("ended", () => setPlaying((current) => (current === itemId ? null : current)));
    audio.current = player;
    setPlaying(itemId);
    void player.play().catch(() => setPlaying(null));
  }

  async function add(itemId: string) {
    setBusy(itemId);
    setError(null);
    try {
      const result = await addLibraryItem(projectId, itemId);
      setAdded((current) => new Set(current).add(itemId));
      onAdded(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby={`${id}-title`} className="space-y-3 rounded-block border border-border bg-surface-2/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 id={`${id}-title`} className="flex items-center gap-1.5 text-small font-semibold text-foreground">
            <LibraryIcon aria-hidden="true" className="size-3.5 text-accent-soft" />
            PeakSift library
          </h4>
          <p className="text-caption text-pretty text-subtle">Free to use in your videos — no credit needed.</p>
        </div>
        <button
          type="button"
          onClick={() => setCredits(true)}
          className="inline-flex min-h-11 shrink-0 items-center text-caption text-accent-soft underline-offset-2 hover:underline pointer-fine:min-h-0"
        >
          Sources & licences
        </button>
      </div>

      {loadError ? (
        <p className="text-caption text-amber-200">The library could not be loaded. {loadError}</p>
      ) : !library ? (
        <p className="flex items-center gap-2 text-caption text-subtle">
          <Loader2 aria-hidden="true" className="size-3.5 animate-spin" /> Loading the library…
        </p>
      ) : !library.available ? (
        <p className="text-caption text-pretty text-subtle">
          The library isn&apos;t installed on this server yet (an administrator installs it once).
        </p>
      ) : (
        <>
          {kinds.length > 1 ? (
            <SegmentedControl
              label="Library section"
              size="sm"
              options={kinds.map((k) => ({ value: k, label: KIND_LABELS[k] }))}
              value={kind}
              onChange={(next) => {
                setKind(next);
                setCategory(null);
              }}
            />
          ) : null}
          <label className="relative block">
            <span className="sr-only">Search the library</span>
            <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-subtle" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                kind === "sticker"
                  ? "Search stickers"
                  : kind === "overlay"
                    ? "Search effects (confetti, fire…)"
                    : kind === "music"
                      ? "Search music"
                      : "Search sounds (whoosh, pop, boom…)"
              }
              className="h-9 w-full rounded-control border border-border bg-background pr-3 pl-8 text-small text-foreground placeholder:text-subtle focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:h-11"
            />
          </label>
          {categories.length > 1 ? (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Categories">
              {[null, ...categories].map((c) => (
                <button
                  key={c ?? "all"}
                  type="button"
                  aria-pressed={category === c}
                  onClick={() => setCategory(c)}
                  className={`inline-flex h-7 items-center rounded-full border px-2.5 text-caption transition-colors pointer-coarse:h-11 ${
                    category === c ? "border-accent/60 bg-accent/15 text-foreground" : "border-border text-muted hover:text-foreground"
                  }`}
                >
                  {c ? categoryLabel(c) : "All"}
                </button>
              ))}
            </div>
          ) : null}

          {kind === "overlay" ? (
            <ul className="grid max-h-80 grid-cols-3 gap-2 overflow-y-auto pr-1 [scrollbar-width:thin]" aria-label="Animated overlays">
              {shown.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => void add(item.id)}
                    disabled={busy !== null}
                    aria-label={`Add ${item.title}`}
                    title={item.title}
                    className="group relative block w-full overflow-hidden rounded-control border border-border bg-[#2b3a55] transition-colors hover:border-accent/60 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60"
                  >
                    {/* A muted looping preview of the effect over a neutral backdrop. */}
                    <video
                      src={libraryContentUrl(item.id)}
                      muted
                      loop
                      autoPlay
                      playsInline
                      preload="metadata"
                      aria-hidden="true"
                      className="aspect-[9/16] w-full object-cover"
                    />
                    <span className="absolute inset-x-0 bottom-0 truncate bg-black/55 px-1.5 py-1 text-left text-caption text-white">
                      {item.title}
                    </span>
                    {busy === item.id ? <Loader2 aria-hidden="true" className="absolute top-1.5 right-1.5 size-4 animate-spin text-white" /> : null}
                    {added.has(item.id) ? <Check aria-hidden="true" className="absolute top-1.5 right-1.5 size-4 rounded-full bg-success p-0.5 text-black" /> : null}
                  </button>
                </li>
              ))}
              {!shown.length ? <li className="col-span-3 px-1 py-2 text-caption text-subtle">Nothing matches. Try another word.</li> : null}
            </ul>
          ) : kind === "sticker" ? (
            <ul className="grid max-h-72 grid-cols-4 gap-2 overflow-y-auto pr-1 [scrollbar-width:thin]" aria-label="Stickers">
              {shown.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => void add(item.id)}
                    disabled={busy !== null}
                    aria-label={`Add ${item.title}`}
                    title={item.title}
                    className="relative flex aspect-square w-full items-center justify-center rounded-control border border-border bg-[repeating-conic-gradient(#2a2a30_0_25%,#1f1f24_0_50%)] bg-[length:12px_12px] p-1.5 transition-colors hover:border-accent/60 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={libraryContentUrl(item.id)} alt="" loading="lazy" className="size-full object-contain" />
                    {busy === item.id ? <Loader2 aria-hidden="true" className="absolute size-4 animate-spin text-white" /> : null}
                    {added.has(item.id) ? <Check aria-hidden="true" className="absolute right-1 bottom-1 size-3.5 rounded-full bg-success p-0.5 text-black" /> : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="max-h-72 space-y-1 overflow-y-auto pr-1 [scrollbar-width:thin]" aria-label={KIND_LABELS[kind]}>
              {shown.map((item) => (
                <li key={item.id} className="flex items-center gap-2 rounded-control px-1 py-0.5 hover:bg-surface-3/40">
                  <button
                    type="button"
                    onClick={() => listen(item.id)}
                    aria-label={playing === item.id ? `Stop ${item.title}` : `Listen to ${item.title}`}
                    className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border text-foreground hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:size-11"
                  >
                    {playing === item.id ? <Pause aria-hidden="true" className="size-3.5" /> : <Play aria-hidden="true" className="size-3.5" />}
                  </button>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-small text-foreground">{item.title}</span>
                    <span className="block truncate text-caption text-subtle">
                      {categoryLabel(item.category)} · {lengthLabel(item.duration_seconds)}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => void add(item.id)}
                    disabled={busy !== null}
                    className="inline-flex h-8 shrink-0 items-center gap-1 rounded-control border border-border-strong px-2.5 text-caption font-medium text-foreground hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60 pointer-coarse:h-11"
                  >
                    {busy === item.id ? (
                      <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
                    ) : added.has(item.id) ? (
                      <Check aria-hidden="true" className="size-3.5 text-success" />
                    ) : (
                      <Plus aria-hidden="true" className="size-3.5" />
                    )}
                    {kind === "music" ? "Use" : "Add"}
                  </button>
                </li>
              ))}
              {!shown.length ? <li className="px-1 py-2 text-caption text-subtle">Nothing matches. Try another word.</li> : null}
            </ul>
          )}
          {error ? <p role="alert" className="text-caption text-amber-200">{error}</p> : null}
        </>
      )}

      <Dialog open={credits} onClose={() => setCredits(false)} title="Library sources & licences" description="Everything in the PeakSift library may be used in your published videos, including commercially, without a credit.">
        <ul className="space-y-3 text-small">
          {(library?.sources ?? []).map((source) => (
            <li key={source.name}>
              <a href={source.url} target="_blank" rel="noreferrer noopener" className="font-medium text-foreground underline-offset-2 hover:underline">
                {source.name}
              </a>
              <span className="text-muted"> · {source.licence}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-caption text-pretty text-subtle">
          Microsoft Fluent Emoji: Copyright (c) Microsoft Corporation, MIT licence. Sounds from Kenney, music from OpenGameArt.org
          authors and the animated overlays (made by PeakSift from Kenney&apos;s Particle Pack) are dedicated to the public domain
          (CC0). Each item&apos;s source and licence are kept on the asset when you add it.
        </p>
      </Dialog>
    </section>
  );
}
