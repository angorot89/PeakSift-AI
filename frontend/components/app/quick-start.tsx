"use client";

import { ArrowRight, Captions, Sparkles, UploadCloud, type LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { FormError } from "@/components/ui/form-error";
import { WorkingState } from "@/components/ui/progress";
import { useToast } from "@/components/ui/toast";
import { ApiError, errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { QUICK_START_NAME_MAX, nameFromFile, quickStartNotice } from "@/lib/quick-start";
import { ACCEPT_ATTRIBUTE, ACCEPTED_LABEL, hasAcceptedExtension, quickStart } from "@/lib/videos";

type Phase = "idle" | "uploading" | "processing";

const AFTER: { icon: LucideIcon; text: string }[] = [
  { icon: UploadCloud, text: "Uploads your video" },
  { icon: Captions, text: "Transcribes every word" },
  { icon: Sparkles, text: "Finds the moments worth clipping" },
];

function problemWith(file: File): string | null {
  if (!hasAcceptedExtension(file.name)) return `Choose an ${ACCEPTED_LABEL} file.`;
  if (file.size === 0) return "That file is empty.";
  return null;
}

/**
 * Home's one step: drop a long video and PeakSift does the rest — names the project,
 * transcribes it and finds the moments — so the creator's next click is reviewing them.
 * `market` is only passed where the page has already chosen one (Morocco Mode).
 */
export function QuickStart({ market, className = "" }: { market?: string; className?: string }) {
  const router = useRouter();
  const toast = useToast();
  const { setUser } = useAuth();
  const inputId = useId();
  const headingId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const busy = phase !== "idle";

  function choose(files: FileList | null) {
    const chosen = files?.[0] ?? null;
    if (!chosen) return;
    const problem = problemWith(chosen);
    setError(problem);
    setFile(problem ? null : chosen);
    if (!problem) setName(nameFromFile(chosen.name));
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

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;
    setError(null);
    setProgress(0);
    setPhase("uploading");
    try {
      const result = await quickStart(file, { name, market }, (percent) => {
        setProgress(percent);
        if (percent >= 100) setPhase("processing");
      });
      const notice = quickStartNotice({
        video_status: result.video.status,
        transcription_started: result.transcription_started,
      });
      if (notice) toast(notice);
      router.push(`/projects/${result.project.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      setPhase("idle");
      setError(errorMessage(err));
    }
  }

  return (
    <section
      aria-labelledby={headingId}
      className={`rounded-card border border-border bg-surface p-4 sm:p-5 ${className}`}
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-block bg-surface-3 text-foreground">
          <Sparkles aria-hidden="true" className="size-5" />
        </span>
        <div className="min-w-0">
          <h2 id={headingId} className="text-title">
            Start from a video
          </h2>
          <p className="mt-0.5 text-sm text-pretty text-muted">
            Drop a stream, podcast or interview. PeakSift transcribes it and finds your best moments — nothing to set up.
          </p>
        </div>
      </div>

      {!file ? (
        <label
          htmlFor={inputId}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={`mt-4 flex min-h-28 cursor-pointer flex-col items-center justify-center gap-1.5 rounded-block border border-dashed px-5 py-6 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
            dragging ? "border-accent bg-accent/10" : "border-border-strong bg-background hover:border-subtle"
          }`}
        >
          <input
            id={inputId}
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            onChange={handleChange}
            className="sr-only"
            aria-describedby={`${inputId}-hint`}
          />
          <UploadCloud aria-hidden="true" className="size-6 text-accent-soft" />
          <span className="font-medium text-foreground">
            Drop a video here, or <span className="text-foreground underline decoration-accent decoration-2 underline-offset-4">browse</span>
          </span>
          <span id={`${inputId}-hint`} className="text-small text-muted">
            {ACCEPTED_LABEL}
          </span>
        </label>
      ) : (
        <form onSubmit={start} noValidate className="mt-4 space-y-4">
          <div className="rounded-block border border-border bg-surface px-4 py-3">
            <p className="font-medium break-all text-foreground">{file.name}</p>
            <p className="text-small text-muted">{formatBytes(file.size)}</p>
          </div>

          {!busy ? (
            <>
              <Field
                id={`${inputId}-name`}
                label="Project name"
                dir="auto"
                autoComplete="off"
                maxLength={QUICK_START_NAME_MAX}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <ol className="grid gap-2 text-small text-muted sm:grid-cols-3">
                {AFTER.map((step, index) => (
                  <li key={step.text} className="flex items-center gap-2">
                    <step.icon aria-hidden="true" className="size-4 shrink-0 text-accent-soft" />
                    <span>
                      <span className="tabular text-subtle">{index + 1}. </span>
                      {step.text}
                    </span>
                  </li>
                ))}
              </ol>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setFile(null);
                    setError(null);
                  }}
                >
                  Choose another video
                </Button>
                <Button type="submit">
                  Find my moments
                  <ArrowRight aria-hidden="true" />
                </Button>
              </div>
            </>
          ) : null}

          {phase === "uploading" ? (
            <WorkingState
              label="Uploading your video"
              progress={progress}
              progressLabel="Upload progress"
              detail="Keep this tab open until the upload finishes. After that you can leave."
            />
          ) : null}
          {phase === "processing" ? (
            <WorkingState label="Checking the video and starting the transcription" detail="Upload complete." />
          ) : null}
        </form>
      )}

      {error ? (
        <div className="mt-3">
          <FormError>{error}</FormError>
        </div>
      ) : null}
    </section>
  );
}
