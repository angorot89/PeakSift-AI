"use client";

import { Film, RefreshCw, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CandidateReview } from "@/components/app/candidate-review";
import { ClipDetectionPanel } from "@/components/app/clip-detection-panel";
import { GeneratedClipsPanel } from "@/components/app/generated-clips-panel";
import { useWorkflowReport, useWorkflowReporter, type StepState } from "@/components/app/project-workflow";
import { ErrorState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { TranscriptionPanel } from "@/components/app/transcription-panel";
import { VideoUpload } from "@/components/app/video-upload";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { MediaFrame } from "@/components/ui/media-frame";
import { Panel } from "@/components/ui/panel";
import { WorkingState } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, formatDate, formatDuration, formatFps } from "@/lib/format";
import { listVideoClips, type GeneratedClip } from "@/lib/clips";
import type { Transcription } from "@/lib/transcription";
import { useApi } from "@/lib/use-api";
import { listProjectVideos, videoContentUrl, type Video } from "@/lib/videos";

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-subtle">{label}</dt>
      <dd className="tabular mt-0.5 truncate text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

function SourceDetails({ video }: { video: Video }) {
  const facts: Array<[string, string]> = [];
  if (video.duration_seconds != null) facts.push(["Duration", formatDuration(video.duration_seconds)]);
  if (video.width != null && video.height != null) facts.push(["Resolution", `${video.width} × ${video.height}`]);
  facts.push(["File size", formatBytes(video.file_size)]);
  facts.push(["Uploaded", formatDate(video.created_at)]);

  const technical: Array<[string, string]> = [["File type", video.content_type]];
  if (video.fps != null) technical.push(["Frame rate", formatFps(video.fps)]);
  if (video.video_codec) technical.push(["Video codec", video.video_codec]);
  if (video.audio_codec) technical.push(["Audio codec", video.audio_codec]);

  return (
    <div className="min-w-0 space-y-5">
      <p className="text-sm font-medium break-all text-foreground">{video.original_filename}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        {facts.map(([label, value]) => (
          <Fact key={label} label={label} value={value} />
        ))}
      </dl>
      <details className="group rounded-lg border border-border">
        <summary className="cursor-pointer list-none px-3 py-2 text-xs text-muted transition-colors select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
          <span className="group-open:hidden">Show technical details</span>
          <span className="hidden group-open:inline">Hide technical details</span>
        </summary>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border px-3 py-3">
          {technical.map(([label, value]) => (
            <Fact key={label} label={label} value={value} />
          ))}
        </dl>
      </details>
    </div>
  );
}

function uploadState(video: Video | null, loading: boolean): StepState {
  if (loading) return "unknown";
  if (!video) return "todo";
  if (video.status === "ready") return "done";
  if (video.status === "failed") return "failed";
  return "active";
}

/**
 * The project workspace: one numbered section per workflow stage. Owns the state that
 * several sections share (the video, its transcription, and its generated clips).
 */
export function ProjectWorkspace({ projectId }: { projectId: string }) {
  const load = useCallback(() => listProjectVideos(projectId), [projectId]);
  const { data: videos, error, loading, reload } = useApi(load);
  const [replacing, setReplacing] = useState(false);
  const latest = videos?.[0] ?? null;
  const ready = latest?.status === "ready" && !replacing;

  useWorkflowReport("upload", uploadState(latest, loading));
  // Later stages only report from their own sections; without a usable video they have not started.
  const report = useWorkflowReporter();
  useEffect(() => {
    if (loading || ready) return;
    for (const key of ["transcribe", "detect", "generate", "edit"] as const) report?.(key, "todo");
  }, [loading, ready, report]);

  const [transcriptState, setTranscriptState] = useState<{ transcription: Transcription | null; loaded: boolean }>({
    transcription: null,
    loaded: false,
  });
  const onTranscriptionChange = useCallback(
    (transcription: Transcription | null, loaded: boolean) => setTranscriptState({ transcription, loaded }),
    [],
  );

  // candidate_id → clip, shared by the candidate cards and the Generated clips section.
  const [clips, setClips] = useState<Map<string, GeneratedClip> | null>(null);
  const [clipsKnown, setClipsKnown] = useState(false);
  const videoId = ready ? latest.id : null;
  useEffect(() => {
    if (!videoId) return;
    let cancelled = false;
    listVideoClips(projectId, videoId)
      .then((page) => {
        if (cancelled) return;
        setClips(new Map(page.clips.map((clip) => [clip.candidate_id, clip])));
        setClipsKnown(true);
      })
      .catch(() => {
        if (!cancelled) setClips(new Map()); // each card then fetches its own clip state
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, videoId]);
  const rememberClip = useCallback((clip: GeneratedClip) => {
    setClips((previous) => new Map(previous ?? []).set(clip.candidate_id, clip));
  }, []);

  let body;
  if (loading) {
    body = (
      <div role="status" aria-label="Loading source video" className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Skeleton className="aspect-video w-full rounded-xl" />
        <div className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-16 w-full" />
        </div>
      </div>
    );
  } else if (error) {
    body = <ErrorState title="The source video could not be loaded" message={error} onRetry={reload} />;
  } else if (!latest || replacing) {
    body = (
      <div className="space-y-4">
        {!latest ? (
          <p className="text-sm text-muted">Upload your first video to start finding clips.</p>
        ) : null}
        <VideoUpload
          projectId={projectId}
          onUploaded={() => {
            setReplacing(false);
            reload();
          }}
          onCancel={latest ? () => setReplacing(false) : undefined}
        />
      </div>
    );
  } else if (latest.status === "failed") {
    body = (
      <InlineAlert
        title="This file could not be read as a video"
        action={
          <Button variant="secondary" size="sm" onClick={() => setReplacing(true)}>
            <Upload aria-hidden="true" />
            Upload a different file
          </Button>
        }
      >
        {latest.error_message ?? "The upload was stored but is not readable media. Try a different export."}
      </InlineAlert>
    );
  } else if (latest.status !== "ready") {
    body = <WorkingState label="Reading video metadata" detail={latest.original_filename} />;
  } else {
    body = (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <MediaFrame icon={Film} label="Source preview">
          {/* The browser streams with Range requests and the session cookie (same-site). */}
          <video
            controls
            preload="metadata"
            src={videoContentUrl(latest.id)}
            className="aspect-video w-full bg-black"
            aria-label={`Preview of ${latest.original_filename}`}
          />
        </MediaFrame>
        <SourceDetails video={latest} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Panel
        id="source"
        step="1"
        title="Source video"
        description="The long recording this project is built from."
        status={latest && !replacing ? <StatusBadge status={latest.status} /> : undefined}
        actions={
          latest && !replacing && latest.status === "ready" ? (
            <Button variant="ghost" size="sm" onClick={() => setReplacing(true)}>
              <RefreshCw aria-hidden="true" />
              Replace
            </Button>
          ) : undefined
        }
      >
        {body}
      </Panel>

      {ready ? (
        <>
          <TranscriptionPanel
            projectId={projectId}
            videoId={latest.id}
            onTranscriptionChange={onTranscriptionChange}
          />
          <ClipDetectionPanel
            projectId={projectId}
            videoId={latest.id}
            transcription={transcriptState.transcription}
            transcriptionLoaded={transcriptState.loaded}
            renderResults={(run) => (
              <CandidateReview
                projectId={projectId}
                videoId={latest.id}
                run={run}
                clips={clips}
                clipsKnown={clipsKnown}
                onClipChange={rememberClip}
              />
            )}
          />
          <GeneratedClipsPanel projectId={projectId} clips={clips} />
        </>
      ) : null}
    </div>
  );
}
