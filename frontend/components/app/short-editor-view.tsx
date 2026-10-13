"use client";

import { ArrowLeft, CheckCircle2, Clapperboard, Download, Eye, Plus, RotateCcw, ScanFace, Smartphone, Wand2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { CaptionSwitch, LayoutPicker, PositionPicker, StylePicker } from "@/components/app/editor/controls";
import { NineBySixteenFrame, PreviewStage, ReframedPreview, type Framing } from "@/components/app/editor/preview-stage";
import { SmartReframePanel, type FramingMode } from "@/components/app/editor/smart-reframe";
import { VersionList } from "@/components/app/editor/versions";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { buttonClasses } from "@/components/ui/button-styles";
import { InlineAlert } from "@/components/ui/inline-alert";
import { WorkingState } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, errorMessage } from "@/lib/api";
import { clipContentUrl, listVideoClips, type GeneratedClip } from "@/lib/clips";
import {
  captionSummary,
  createEdit,
  editContentUrl,
  editDownloadUrl,
  editStageLabel,
  friendlyEditError,
  isEditActive,
  layoutLabel,
  listEdits,
  positionLabel,
  retryEdit,
  sameSettings,
  styleLabel,
  type CaptionPosition,
  type CaptionStyle,
  type ClipEdit,
  type EditRequest,
  type PickableLayout,
} from "@/lib/edits";
import { formatDuration } from "@/lib/format";
import { getProject, isProjectId, type Project } from "@/lib/projects";
import {
  getAnalysis,
  getCropPath,
  getCurrentAnalysis,
  isAnalysisActive,
  retryAnalysis,
  startAnalysis,
  type CropPath,
  type ReframeAnalysis,
} from "@/lib/reframe";
import { getTranscriptPage } from "@/lib/transcription";
import { useApi } from "@/lib/use-api";
import { listProjectVideos } from "@/lib/videos";

const POLL_INTERVAL_MS = 4000;
const FALLBACK_CAPTION = "Your captions appear here";

/** Real words from the transcript at the start of the clip, trimmed like a caption cue. */
async function sampleCaption(projectId: string, clip: GeneratedClip): Promise<string> {
  const page = await getTranscriptPage(projectId, clip.video_id, 0, 500);
  const segment = page.segments.find((s) => s.end > clip.start_time && s.start < clip.end_time);
  if (!segment) return FALLBACK_CAPTION;
  const words: string[] = [];
  for (const word of segment.text.split(/\s+/).filter(Boolean)) {
    if (words.length >= 7 || [...words, word].join(" ").length > 32) break;
    words.push(word);
  }
  return words.length ? words.join(" ") : FALLBACK_CAPTION;
}

function Editor({ project, clip }: { project: Project; clip: GeneratedClip }) {
  const { setUser } = useAuth();
  const id = useId();
  const [layout, setLayout] = useState<PickableLayout>("blur_background");
  const [framingMode, setFramingMode] = useState<FramingMode>("auto");
  const [focus, setFocus] = useState({ x: 0.5, y: 0.5 });
  // undefined = still loading, null = never analyzed with the server's current configuration.
  const [analysis, setAnalysis] = useState<ReframeAnalysis | null | undefined>(undefined);
  const [cropPath, setCropPath] = useState<CropPath | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [captions, setCaptions] = useState(true);
  const [style, setStyle] = useState<CaptionStyle>("bold");
  const [position, setPosition] = useState<CaptionPosition>("bottom");
  const [edits, setEdits] = useState<ClipEdit[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<"preview" | "rendered">("preview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [justFinished, setJustFinished] = useState(false);
  const [busy, setBusy] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [sample, setSample] = useState(FALLBACK_CAPTION);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );

  const stageRef = useRef<HTMLDivElement>(null);
  // The version just started; read through a ref so polling does not restart on change.
  const pendingRef = useRef<string | null>(null);
  pendingRef.current = pendingId;

  const refresh = useCallback(
    () =>
      listEdits(project.id, clip.video_id, clip.id)
        .then((page) => {
          setEdits(page.edits);
          setLoadError(null);
          // When the version just started becomes ready, put the real output on the stage.
          const finished = page.edits.find((e) => e.id === pendingRef.current && e.status === "ready");
          if (finished) {
            setSelectedId(finished.id);
            setMode("rendered");
            setJustFinished(true);
            setPendingId(null);
            stageRef.current?.scrollIntoView({ block: "nearest" });
          }
        })
        .catch((err: unknown) => setLoadError(handleError(err))),
    [project.id, clip.video_id, clip.id, handleError],
  );

  useEffect(() => {
    void refresh();
    sampleCaption(project.id, clip)
      .then(setSample)
      .catch(() => setSample(FALLBACK_CAPTION));
  }, [refresh, project.id, clip]);

  // Poll only while some version is really rendering; stop when all are settled.
  const anyActive = !!edits?.some((e) => isEditActive(e.status) && !e.is_stale);
  useEffect(() => {
    if (!anyActive) return;
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [anyActive, refresh]);

  // ---- smart framing analysis -------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    getCurrentAnalysis(project.id, clip.video_id, clip.id)
      .then((current) => {
        if (!cancelled) setAnalysis(current);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setAnalysis(null);
        setAnalysisError(handleError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, clip.video_id, clip.id, handleError]);

  // Poll only while the analysis is really running.
  const analysisId = analysis?.id ?? null;
  const analysisRunning = !!analysis && isAnalysisActive(analysis.status) && !analysis.is_stale;
  useEffect(() => {
    if (!analysisRunning || !analysisId) return;
    const timer = window.setInterval(() => {
      getAnalysis(project.id, clip.video_id, clip.id, analysisId)
        .then(setAnalysis)
        .catch((err: unknown) => setAnalysisError(handleError(err)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [analysisRunning, analysisId, project.id, clip.video_id, clip.id, handleError]);

  // The crop path drives the live preview once the analysis has completed.
  const analysisDone = analysis?.status === "completed";
  useEffect(() => {
    if (!analysisDone || !analysisId) return;
    let cancelled = false;
    getCropPath(project.id, clip.video_id, clip.id, analysisId)
      .then((path) => {
        if (!cancelled) setCropPath(path);
      })
      .catch(() => {
        if (!cancelled) setCropPath(null); // the preview stays centered; rendering is unaffected
      });
    return () => {
      cancelled = true;
    };
  }, [analysisDone, analysisId, project.id, clip.video_id, clip.id]);

  async function analyze(retrying: boolean) {
    if (analysisBusy) return;
    setAnalysisBusy(true);
    setAnalysisError(null);
    try {
      const next =
        retrying && analysis
          ? await retryAnalysis(project.id, clip.video_id, clip.id, analysis.id)
          : await startAnalysis(project.id, clip.video_id, clip.id);
      setCropPath(null);
      setAnalysis(next);
    } catch (err) {
      setAnalysisError(handleError(err));
    } finally {
      setAnalysisBusy(false);
    }
  }

  const smart = layout === "smart_reframe";
  const manual = smart && framingMode === "manual";
  const sourceWidth = clip.width ?? cropPath?.source_width ?? analysis?.source_width ?? null;
  const sourceHeight = clip.height ?? cropPath?.source_height ?? analysis?.source_height ?? null;
  const pathKeyframes = analysisDone && cropPath?.analysis_id === analysisId ? cropPath.keyframes : null;
  const framing: Framing = useMemo(
    () =>
      manual
        ? { kind: "focus", x: focus.x, y: focus.y }
        : pathKeyframes
          ? { kind: "path", keyframes: pathKeyframes }
          : { kind: "center" },
    [manual, focus, pathKeyframes],
  );
  // Automatic framing can render only from a completed analysis of this clip.
  const awaitingAnalysis = smart && !manual && !analysisDone;

  const request: EditRequest = useMemo(
    () => ({
      aspect_ratio: "9:16",
      layout: manual ? "manual_crop" : layout,
      captions_enabled: captions,
      ...(captions ? { caption_style: style, caption_position: position } : {}),
      ...(smart && !manual && analysisDone && analysisId ? { reframe_analysis_id: analysisId } : {}),
      ...(manual ? { focus_x: focus.x, focus_y: focus.y } : {}),
    }),
    [layout, manual, smart, captions, style, position, analysisDone, analysisId, focus],
  );
  const match = awaitingAnalysis ? null : (edits?.find((e) => sameSettings(e, request)) ?? null);
  const matchActive = !!match && isEditActive(match.status) && !match.is_stale;
  const matchStuck = !!match && (match.status === "failed" || (isEditActive(match.status) && match.is_stale));
  const readyEdits = edits?.filter((e) => e.status === "ready") ?? [];
  const selected = edits?.find((e) => e.id === selectedId && e.status === "ready") ?? null;

  function upsert(edit: ClipEdit) {
    setEdits((current) => {
      const list = current ?? [];
      return list.some((e) => e.id === edit.id) ? list.map((e) => (e.id === edit.id ? edit : e)) : [edit, ...list];
    });
  }

  async function retry(edit: ClipEdit) {
    setRetryingId(edit.id);
    setActionError(null);
    try {
      const updated = await retryEdit(project.id, clip.video_id, clip.id, edit.id);
      upsert(updated);
      setPendingId(updated.id);
    } catch (err) {
      setActionError(handleError(err));
    } finally {
      setRetryingId(null);
    }
  }

  async function render() {
    if (busy || matchActive || awaitingAnalysis) return; // no duplicate submissions (the API deduplicates too)
    if (match?.status === "ready") {
      showRendered(match);
      return;
    }
    if (match && matchStuck) {
      await retry(match);
      return;
    }
    setBusy(true);
    setActionError(null);
    setJustFinished(false);
    try {
      const edit = await createEdit(project.id, clip.video_id, clip.id, request);
      upsert(edit);
      setPendingId(edit.id);
    } catch (err) {
      setActionError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  function showRendered(edit: ClipEdit) {
    setSelectedId(edit.id);
    setMode("rendered");
    setJustFinished(false);
  }

  const backToProject = `/projects/${project.id}#generated`;
  const renderedName = selected ? `${layoutLabel(selected.layout)} · ${captionSummary(selected)}` : "";
  const settingsSummary = `${layoutLabel(request.layout)} · ${
    captions ? `${styleLabel(style)} captions · ${positionLabel(position)}` : "No captions"
  }`;

  // ---- primary action area -------------------------------------------------------------
  let action;
  if (matchActive && match) {
    action = (
      <div className="rounded-xl border border-border bg-surface-2 p-3.5">
        <WorkingState
          label={editStageLabel(match).replace("…", "")}
          progress={match.status === "queued" ? null : match.progress_percent}
          progressLabel="Render progress"
          detail="Rendering short on the server. You can keep adjusting settings or leave this page."
        />
      </div>
    );
  } else if (match?.status === "ready") {
    action = (
      <div className="space-y-2">
        <Button size="lg" variant="secondary" className="w-full" onClick={() => showRendered(match)}>
          <Eye aria-hidden="true" />
          View this version
        </Button>
        <p className="text-center text-xs text-subtle">You already rendered these settings.</p>
      </div>
    );
  } else if (matchStuck && match) {
    action = (
      <div className="space-y-3">
        <InlineAlert title={match.status === "failed" ? "Render failed" : "Render stalled"}>
          We couldn&apos;t generate this version of your short.
          <span className="block text-xs text-subtle">
            {match.status === "failed" ? friendlyEditError(match) : "The worker stopped reporting progress."}
          </span>
        </InlineAlert>
        <Button size="lg" className="w-full" onClick={() => void retry(match)} disabled={retryingId === match.id}>
          <RotateCcw aria-hidden="true" />
          {retryingId === match.id ? "Retrying…" : "Retry render"}
        </Button>
      </div>
    );
  } else if (awaitingAnalysis) {
    action = (
      <div className="space-y-2">
        <Button size="lg" className="w-full" disabled>
          <Wand2 aria-hidden="true" />
          Render short
        </Button>
        <p className="text-center text-xs text-subtle">
          {analysis && isAnalysisActive(analysis.status) && !analysis.is_stale
            ? "Available when the framing analysis finishes."
            : "Analyze the framing first, or set a focal point."}
        </p>
      </div>
    );
  } else {
    action = (
      <Button size="lg" className="w-full" onClick={() => void render()} disabled={busy || edits === null}>
        <Wand2 aria-hidden="true" />
        {busy ? "Starting…" : "Render short"}
      </Button>
    );
  }

  return (
    <>
      <PageHeader
        back={{ href: backToProject, label: project.name }}
        title="Short-form editor"
        description={
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span className="text-foreground">{clip.title}</span>
            <span className="tabular text-subtle">· {formatDuration(clip.duration_seconds)} clip</span>
          </span>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-8">
        {/* Stage: the video is the focal point. */}
        <section aria-label="Stage" ref={stageRef} className="min-w-0 scroll-mt-20 lg:col-start-1 lg:row-start-1">
          <div className="rounded-2xl border border-border bg-[radial-gradient(ellipse_at_top,rgb(255_255_255/0.04),transparent_60%)] bg-surface p-4 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5" role="group" aria-label="Stage view">
                <button
                  type="button"
                  aria-pressed={mode === "preview"}
                  onClick={() => setMode("preview")}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                    mode === "preview" ? "bg-surface-3 text-foreground shadow-sm" : "text-muted hover:text-foreground"
                  }`}
                >
                  <Eye aria-hidden="true" className="size-3.5" />
                  Preview
                </button>
                <button
                  type="button"
                  aria-pressed={mode === "rendered"}
                  disabled={readyEdits.length === 0}
                  onClick={() => {
                    const target = selected ?? readyEdits[0];
                    if (target) showRendered(target);
                  }}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40 ${
                    mode === "rendered" ? "bg-surface-3 text-foreground shadow-sm" : "text-muted hover:text-foreground"
                  }`}
                >
                  <Smartphone aria-hidden="true" className="size-3.5" />
                  Rendered short
                </button>
              </div>
              <span className="tabular text-xs text-subtle">9:16 · 1080 × 1920</span>
            </div>

            {mode === "rendered" && selected ? (
              <div className="animate-fade-in space-y-4">
                <NineBySixteenFrame label={`Rendered short: ${renderedName}`}>
                  <video
                    key={selected.id}
                    controls
                    playsInline
                    preload="metadata"
                    src={editContentUrl(selected.id)}
                    className="size-full bg-black object-contain"
                    aria-label={`Rendered short: ${renderedName}`}
                  />
                </NineBySixteenFrame>
                {justFinished ? (
                  <p role="status" className="flex items-center justify-center gap-2 text-sm text-emerald-200">
                    <CheckCircle2 aria-hidden="true" className="size-4" />
                    Your short is ready.
                  </p>
                ) : null}
                <div className="text-center">
                  <p className="text-sm font-medium text-foreground">{renderedName}</p>
                  <p className="tabular text-xs text-subtle">
                    Rendered MP4 · {selected.duration_seconds != null ? formatDuration(selected.duration_seconds) : ""} · 1080 × 1920
                  </p>
                </div>
                <div className="flex flex-col items-stretch justify-center gap-2 sm:flex-row sm:items-center">
                  <a
                    href={editDownloadUrl(selected.id)}
                    download
                    className={buttonClasses("primary", "md")}
                    aria-label={`Download short — ${renderedName}`}
                  >
                    <Download aria-hidden="true" />
                    Download short
                  </a>
                  <Button variant="secondary" onClick={() => setMode("preview")}>
                    <Plus aria-hidden="true" />
                    Create another version
                  </Button>
                  <Link href={backToProject} className={buttonClasses("ghost", "md")}>
                    <ArrowLeft aria-hidden="true" />
                    Back to clip
                  </Link>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="relative">
                  {smart && sourceWidth && sourceHeight ? (
                    <ReframedPreview
                      clipSrc={clipContentUrl(clip.id)}
                      sourceWidth={sourceWidth}
                      sourceHeight={sourceHeight}
                      framing={framing}
                      captions={captions}
                      style={style}
                      position={position}
                      sampleText={sample}
                      badge={
                        framing.kind === "center" ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                            <ScanFace aria-hidden="true" className="size-3" />
                            Centered until framing is analyzed
                          </span>
                        ) : null
                      }
                    />
                  ) : (
                    <PreviewStage
                      clipSrc={clipContentUrl(clip.id)}
                      layout={smart ? "center_crop" : layout}
                      captions={captions}
                      style={style}
                      position={position}
                      sampleText={sample}
                    />
                  )}
                </div>
                <p className="mx-auto max-w-sm text-center text-xs text-pretty text-subtle">
                  Preview only — layout and caption placement are approximate. The rendered MP4 is the final result.
                  {captions ? " The caption shows real words from your transcript." : ""}
                </p>
              </div>
            )}
          </div>
        </section>

        {/* Settings: everything the server accepts, nothing it does not. */}
        <aside
          aria-label="Edit settings"
          className="self-start rounded-2xl border border-border bg-surface lg:sticky lg:top-20 lg:col-start-2 lg:row-span-2 lg:row-start-1"
        >
          <div className="border-b border-border px-4 py-4 sm:px-5">
            <h2 className="text-[15px] font-semibold text-foreground">Edit settings</h2>
            <p className="mt-0.5 text-sm text-muted">Choose how this clip becomes a vertical short.</p>
          </div>
          <div className="space-y-6 px-4 py-5 sm:px-5">
            <div className="space-y-3">
              <LayoutPicker value={layout} onChange={setLayout} name={`${id}-layout`} />
              {smart ? (
                <div className="animate-fade-in space-y-2">
                  <SmartReframePanel
                    name={`${id}-framing`}
                    mode={framingMode}
                    onModeChange={setFramingMode}
                    analysis={analysis}
                    busy={analysisBusy}
                    onAnalyze={() => void analyze(false)}
                    onRetry={() => void analyze(true)}
                    posterSrc={clipContentUrl(clip.id)}
                    sourceWidth={sourceWidth ?? 16}
                    sourceHeight={sourceHeight ?? 9}
                    focusX={focus.x}
                    focusY={focus.y}
                    onFocusChange={(x, y) => setFocus({ x, y })}
                  />
                  {analysisError ? (
                    <InlineAlert title="Smart framing is unavailable">{analysisError}</InlineAlert>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="space-y-4">
              <CaptionSwitch checked={captions} onChange={setCaptions} />
              <StylePicker value={style} onChange={setStyle} name={`${id}-style`} disabled={!captions} />
              <PositionPicker value={position} onChange={setPosition} name={`${id}-position`} disabled={!captions} />
            </div>
          </div>
          <div className="space-y-3 border-t border-border px-4 py-4 sm:px-5">
            <p className="text-xs text-muted">
              <span className="text-subtle">Output: </span>
              {settingsSummary}
            </p>
            {action}
            {actionError ? (
              <InlineAlert title="The render could not start">{actionError}</InlineAlert>
            ) : null}
          </div>
        </aside>

        {/* Versions of this clip, named by their settings. */}
        <section aria-labelledby="versions-heading" className="min-w-0 lg:col-start-1 lg:row-start-2">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="versions-heading" className="text-sm font-medium text-muted">
              Versions{edits && edits.length > 0 ? <span className="tabular text-subtle"> · {edits.length}</span> : null}
            </h2>
          </div>
          {edits === null && !loadError ? (
            <div role="status" aria-label="Loading versions" className="space-y-2">
              <Skeleton className="h-[78px] rounded-xl" />
              <Skeleton className="h-[78px] rounded-xl" />
            </div>
          ) : loadError ? (
            <ErrorState title="Versions could not be loaded" message={loadError} onRetry={() => void refresh()} />
          ) : edits && edits.length > 0 ? (
            <VersionList
              edits={edits}
              selectedId={mode === "rendered" ? selectedId : null}
              onSelect={showRendered}
              onRetry={(edit) => void retry(edit)}
              retryingId={retryingId}
            />
          ) : (
            <EmptyState
              compact
              icon={Smartphone}
              title="No versions yet"
              description="Create a vertical version ready for short-form platforms."
            />
          )}
        </section>
      </div>
    </>
  );
}

/** /projects/[id]/clips/[clipId] — the focused short-form editing workspace for one clip. */
export function ShortEditorView() {
  const { id, clipId } = useParams<{ id: string; clipId: string }>();
  const load = useCallback(async () => {
    if (!isProjectId(id) || !isProjectId(clipId)) throw new ApiError(404, "Clip not found");
    const [project, videos] = await Promise.all([getProject(id), listProjectVideos(id)]);
    for (const video of videos) {
      const page = await listVideoClips(id, video.id);
      const clip = page.clips.find((c) => c.id === clipId);
      if (clip) return { project, clip };
    }
    throw new ApiError(404, "Clip not found");
  }, [id, clipId]);
  const { data, error, loading, reload } = useApi(load);

  if (loading) {
    return (
      <div role="status" aria-label="Loading the editor">
        <Skeleton className="mb-3 h-4 w-32" />
        <Skeleton className="mb-8 h-8 w-72" />
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_400px]">
          <Skeleton className="h-[640px] rounded-2xl" />
          <Skeleton className="h-[640px] rounded-2xl" />
        </div>
      </div>
    );
  }
  if (error || !data) {
    const notFound = error === "Clip not found" || error === "Project not found";
    return (
      <>
        <PageHeader back={{ href: isProjectId(id) ? `/projects/${id}` : "/projects", label: "Project" }} title="Short-form editor" />
        {notFound ? (
          <EmptyState
            icon={Clapperboard}
            title="Clip not found"
            description="This clip does not exist or you do not have access to it."
            action={<ButtonLink href="/projects" variant="secondary">Back to projects</ButtonLink>}
          />
        ) : (
          <ErrorState title="The editor could not be loaded" message={error ?? "Unavailable."} onRetry={reload} />
        )}
      </>
    );
  }
  if (data.clip.status !== "ready") {
    return (
      <>
        <PageHeader back={{ href: `/projects/${id}#generated`, label: data.project.name }} title="Short-form editor" />
        <EmptyState
          icon={Clapperboard}
          title="This clip isn't ready yet"
          description="Short-form edits start from a rendered clip. Come back once it shows Ready."
          action={<ButtonLink href={`/projects/${id}#generated`} variant="secondary">Back to the project</ButtonLink>}
        />
      </>
    );
  }
  return <Editor project={data.project} clip={data.clip} />;
}
