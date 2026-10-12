"use client";

import { useCallback, useState } from "react";
import { ErrorState, LoadingState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { VideoUpload } from "@/components/app/video-upload";
import { Button } from "@/components/ui/button";
import { formatBytes, formatDate, formatDuration, formatFps } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { listProjectVideos, type Video } from "@/lib/videos";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium text-foreground">{value}</dd>
    </div>
  );
}

function VideoDetails({ video, onReplace }: { video: Video; onReplace: () => void }) {
  const rows: Array<[string, string]> = [];
  if (video.duration_seconds != null) rows.push(["Duration", formatDuration(video.duration_seconds)]);
  if (video.width != null && video.height != null)
    rows.push(["Resolution", `${video.width} × ${video.height}`]);
  if (video.fps != null) rows.push(["Frame rate", formatFps(video.fps)]);
  if (video.video_codec) rows.push(["Video codec", video.video_codec]);
  if (video.audio_codec) rows.push(["Audio codec", video.audio_codec]);
  rows.push(["File size", formatBytes(video.file_size)]);
  rows.push(["Uploaded", formatDate(video.created_at)]);

  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:justify-between">
        <div className="min-w-0">
          <p className="font-medium break-all text-foreground">{video.original_filename}</p>
          <p className="mt-1 text-xs text-muted">{video.content_type}</p>
        </div>
        <StatusBadge status={video.status} />
      </div>

      {video.status === "failed" ? (
        <div role="alert" className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-sm text-rose-200">
          <p className="font-medium">Video processing failed</p>
          {video.error_message ? <p className="mt-1">{video.error_message}</p> : null}
          <p className="mt-1 text-rose-200/80">
            The file was stored but could not be read as a video. Try a different export.
          </p>
        </div>
      ) : null}

      <dl className="mt-4 divide-y divide-border">
        {rows.map(([label, value]) => (
          <Row key={label} label={label} value={value} />
        ))}
      </dl>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          Transcription and AI clip detection arrive in later milestones.
        </p>
        <Button variant="secondary" onClick={onReplace}>
          {video.status === "failed" ? "Upload a different file" : "Replace video"}
        </Button>
      </div>
    </div>
  );
}

export function SourceVideo({ projectId }: { projectId: string }) {
  const load = useCallback(() => listProjectVideos(projectId), [projectId]);
  const { data: videos, error, loading, reload } = useApi(load);
  const [replacing, setReplacing] = useState(false);

  const latest = videos?.[0] ?? null;

  return (
    <section aria-labelledby="source-video-heading" className="mt-8">
      <h2 id="source-video-heading" className="mb-4 text-lg font-medium">
        Source video
      </h2>

      {loading ? (
        <LoadingState label="Loading source video…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : latest && !replacing ? (
        <VideoDetails video={latest} onReplace={() => setReplacing(true)} />
      ) : (
        <VideoUpload
          projectId={projectId}
          onUploaded={() => {
            setReplacing(false);
            reload();
          }}
          onCancel={latest ? () => setReplacing(false) : undefined}
        />
      )}
    </section>
  );
}
