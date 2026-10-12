"use client";

import { useId, useState, type ChangeEvent, type DragEvent } from "react";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_LABEL,
  hasAcceptedExtension,
  uploadProjectVideo,
  type Video,
} from "@/lib/videos";

type Phase = "idle" | "uploading" | "processing";

type VideoUploadProps = {
  projectId: string;
  onUploaded: (video: Video) => void;
  onCancel?: () => void;
};

function validate(file: File): string | null {
  if (!hasAcceptedExtension(file.name)) return `Choose an ${ACCEPTED_LABEL} file.`;
  if (file.size === 0) return "That file is empty.";
  return null;
}

export function VideoUpload({ projectId, onUploaded, onCancel }: VideoUploadProps) {
  const inputId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);

  const busy = phase !== "idle";

  function choose(files: FileList | null) {
    const chosen = files?.[0] ?? null;
    if (!chosen) return;
    const problem = validate(chosen);
    setError(problem);
    setFile(problem ? null : chosen);
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    choose(event.target.files);
    event.target.value = ""; // allow re-selecting the same file after an error
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (!busy) choose(event.dataTransfer.files);
  }

  async function upload() {
    if (!file) return;
    setError(null);
    setProgress(0);
    setPhase("uploading");
    try {
      const video = await uploadProjectVideo(projectId, file, (percent) => {
        setProgress(percent);
        if (percent >= 100) setPhase("processing");
      });
      setFile(null);
      setPhase("idle");
      onUploaded(video);
    } catch (err) {
      setPhase("idle");
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-6 py-10 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
          dragging ? "border-accent bg-accent/5" : "border-white/15 hover:border-white/30"
        } ${busy ? "pointer-events-none opacity-60" : ""}`}
      >
        <input
          id={inputId}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          onChange={handleChange}
          disabled={busy}
          className="sr-only"
          aria-describedby={`${inputId}-hint`}
        />
        <span className="font-medium text-foreground">
          Drag and drop a video here, or <span className="text-accent-soft underline">browse</span>
        </span>
        <span id={`${inputId}-hint`} className="text-sm text-muted">
          {ACCEPTED_LABEL}. One long-form source video per project for now.
        </span>
      </label>

      {file ? (
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="font-medium break-all text-foreground">{file.name}</p>
            <p className="text-sm text-muted">{formatBytes(file.size)}</p>
          </div>
          {!busy ? (
            <div className="flex shrink-0 gap-2">
              <Button variant="secondary" onClick={() => setFile(null)}>
                Clear
              </Button>
              <Button onClick={upload}>Upload</Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {phase === "uploading" ? (
        <div className="space-y-2">
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            className="h-2 overflow-hidden rounded-full bg-white/10"
          >
            <div className="h-full bg-accent transition-[width]" style={{ width: `${progress}%` }} />
          </div>
          <p className="text-sm text-muted" aria-live="polite">
            Uploading… {progress}%
          </p>
        </div>
      ) : null}

      {phase === "processing" ? (
        <p className="flex items-center gap-3 text-sm text-muted" role="status">
          <span
            aria-hidden="true"
            className="size-4 animate-spin rounded-full border-2 border-white/15 border-t-accent"
          />
          Upload complete. Reading video metadata…
        </p>
      ) : null}

      <FormError>{error}</FormError>

      {onCancel && !busy ? (
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-muted underline-offset-4 hover:text-foreground hover:underline"
        >
          Keep the current video
        </button>
      ) : null}
    </div>
  );
}
