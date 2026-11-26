"use client";

import { UploadCloud } from "lucide-react";
import { useId, useState, type ChangeEvent, type DragEvent } from "react";
import { WorkingState } from "@/components/ui/progress";
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
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-block border border-dashed px-6 py-10 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
          dragging ? "border-accent bg-accent/5" : "border-border-strong hover:border-subtle hover:bg-surface"
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
        <span className="mb-1 flex size-10 items-center justify-center rounded-block bg-surface-3 text-foreground">
          <UploadCloud aria-hidden="true" className="size-5" />
        </span>
        <span className="font-medium text-foreground">
          Drop a video here, or <span className="text-foreground underline decoration-accent decoration-2 underline-offset-4">browse</span>
        </span>
        <span id={`${inputId}-hint`} className="text-sm text-muted">
          {ACCEPTED_LABEL}. One long-form source video per project for now.
        </span>
      </label>

      {file ? (
        <div className="flex flex-col gap-3 rounded-block border border-border bg-surface-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
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
        <WorkingState label="Uploading video" progress={progress} progressLabel="Upload progress" />
      ) : null}

      {phase === "processing" ? (
        <WorkingState label="Reading video metadata" detail="Upload complete. Checking that the file is readable video." />
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
