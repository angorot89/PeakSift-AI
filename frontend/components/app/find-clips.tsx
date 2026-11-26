"use client";

import { Check, Play, Plus, Search, X } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { inputClasses } from "@/components/ui/input-styles";
import { Panel } from "@/components/ui/panel";
import { Spinner } from "@/components/ui/progress";
import { useToast } from "@/components/ui/toast";
import { VideoFrame } from "@/components/ui/video-frame";
import { errorMessage } from "@/lib/api";
import { findClips, keepFoundClip, type FindClipsResponse, type FoundClip } from "@/lib/find-clips";
import { FIND_CLIPS_EXAMPLES, FIND_CLIPS_QUERY_MAX, canSearch, emptySearch, matchSummary } from "@/lib/find-clips-rules";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { videoContentUrl } from "@/lib/videos";

type Props = {
  projectId: string;
  videoId: string;
  /** A found span became a saved moment: the moments below should reload. */
  onKept: () => void;
};

const spanKey = (found: FoundClip) => `${found.start}-${found.end}`;

function Result({
  found,
  videoId,
  previewing,
  onPreview,
  kept,
  keeping,
  onKeep,
}: {
  found: FoundClip;
  videoId: string;
  previewing: boolean;
  onPreview: () => void;
  kept: boolean;
  keeping: boolean;
  onKeep: () => void;
}) {
  const summary = matchSummary(found);
  return (
    <li className="rounded-block border border-border bg-surface-2/60 p-3 sm:p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-4">
        <div className="w-full shrink-0 sm:w-44">
          {previewing ? (
            <video
              // The media fragment plays only this span of the creator's own source.
              src={`${videoContentUrl(videoId)}#t=${found.start},${found.end}`}
              controls
              autoPlay
              playsInline
              preload="metadata"
              className="aspect-video w-full rounded-control border border-border bg-black"
            />
          ) : (
            <VideoFrame
              src={videoContentUrl(videoId)}
              at={found.start + 0.5}
              ratio="video"
              className="w-full rounded-control border border-border"
            />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="tabular text-small text-muted">
            <time dateTime={`PT${Math.floor(found.start)}S`}>{formatTimestamp(found.start)}</time>
            {" – "}
            <time dateTime={`PT${Math.floor(found.end)}S`}>{formatTimestamp(found.end)}</time>
            <span className="text-subtle"> · {formatDuration(found.duration)}</span>
          </p>
          <blockquote
            dir="auto"
            className="mt-2 line-clamp-4 border-l-2 border-accent/60 pl-3 text-sm leading-relaxed text-pretty break-words text-foreground"
          >
            {found.excerpt}
          </blockquote>
          {summary ? <p className="mt-2 text-small text-muted">{summary}</p> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={onPreview} aria-pressed={previewing}>
              {previewing ? <X aria-hidden="true" /> : <Play aria-hidden="true" />}
              {previewing ? "Close preview" : "Preview"}
            </Button>
            {kept ? (
              <span className="inline-flex min-h-8 items-center gap-1.5 rounded-control bg-success/15 px-2.5 text-small font-medium text-emerald-200">
                <Check aria-hidden="true" className="size-4" />
                In your moments (Saved)
              </span>
            ) : (
              <Button size="sm" onClick={onKeep} disabled={keeping}>
                {keeping ? <Spinner /> : <Plus aria-hidden="true" />}
                Keep this moment
              </Button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

/**
 * Find Clips: describe a moment in plain language and PeakSift shows where it was said — real
 * lines of the creator's own transcript, never a guess. Keeping a result makes it a saved
 * moment, so it flows into clips, Auto Edit and the editor like any other.
 */
export function FindClips({ projectId, videoId, onKept }: Props) {
  const inputId = useId();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [response, setResponse] = useState<FindClipsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [keeping, setKeeping] = useState<string | null>(null);
  const [keptNow, setKeptNow] = useState<Set<string>>(new Set());

  async function run(text: string) {
    const asked = text.trim();
    if (!canSearch(asked) || searching) return;
    setSearching(true);
    setError(null);
    setPreviewing(null);
    try {
      setResponse(await findClips(projectId, videoId, asked));
      setKeptNow(new Set());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSearching(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(query);
  }

  async function keep(found: FoundClip) {
    if (!response) return;
    const key = spanKey(found);
    setKeeping(key);
    setError(null);
    try {
      await keepFoundClip(projectId, videoId, response.query, found);
      setKeptNow((previous) => new Set(previous).add(key));
      toast("Kept. It's under Saved in your moments.");
      onKept();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setKeeping(null);
    }
  }

  const empty = response && response.results.length === 0 ? emptySearch(response.terms, response.related) : null;

  return (
    <Panel
      title="Find clips"
      description="Describe a moment in your own words. PeakSift shows where you said it — real lines from your transcript."
    >
      <form onSubmit={submit} role="search" className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor={inputId} className="sr-only">
          Describe the moment you are looking for
        </label>
        <div className="relative flex-1">
          <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
          <input
            id={inputId}
            type="search"
            dir="auto"
            autoComplete="off"
            enterKeyHint="search"
            maxLength={FIND_CLIPS_QUERY_MAX}
            placeholder="the part where I explain pricing"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className={`${inputClasses} pl-9`}
          />
        </div>
        <Button type="submit" disabled={!canSearch(query) || searching}>
          {searching ? <Spinner /> : <Search aria-hidden="true" />}
          {searching ? "Searching…" : "Find clips"}
        </Button>
      </form>

      {!response && !searching ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-small text-subtle">Try:</span>
          {FIND_CLIPS_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setQuery(example);
                void run(example);
              }}
              className="min-h-8 rounded-full border border-border px-3 text-small text-muted transition-colors hover:border-accent/50 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:min-h-11"
            >
              {example}
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="mt-3">
          <FormError>{error}</FormError>
        </div>
      ) : null}

      <div aria-live="polite">
        {empty ? (
          <div className="mt-4 rounded-block border border-dashed border-border-strong px-4 py-5 text-center">
            <p className="text-title">{empty.title}</p>
            <p className="mx-auto mt-1 max-w-md text-sm text-pretty text-muted">{empty.description}</p>
          </div>
        ) : null}

        {response && response.results.length ? (
          <>
            <p className="mt-4 text-small text-muted">
              {response.results.length} place{response.results.length === 1 ? "" : "s"} found for{" "}
              <span dir="auto" className="text-foreground">
                {response.terms.join(", ")}
              </span>
              {response.related.length ? (
                <>
                  {" "}
                  <span className="text-subtle">· also looked for {response.related.join(", ")}</span>
                </>
              ) : null}
            </p>
            <ul className="mt-3 space-y-3">
              {response.results.map((found) => {
                const key = spanKey(found);
                return (
                  <Result
                    key={key}
                    found={found}
                    videoId={videoId}
                    previewing={previewing === key}
                    onPreview={() => setPreviewing((current) => (current === key ? null : key))}
                    kept={found.candidate_id !== null || keptNow.has(key)}
                    keeping={keeping === key}
                    onKeep={() => void keep(found)}
                  />
                );
              })}
            </ul>
          </>
        ) : null}
      </div>
    </Panel>
  );
}
