"use client";

import { type ReactNode, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { errorMessage } from "@/lib/api";
import {
  LAYOUT_OPTIONS,
  POSITION_OPTIONS,
  STYLE_OPTIONS,
  type CaptionPosition,
  type CaptionStyle,
  type ClipEdit,
  type EditRequest,
  type Layout,
} from "@/lib/edits";

type Option<T extends string> = { value: T; label: string; hint?: string };

/** A radio group rendered as pills; real inputs, so keyboard and screen readers just work. */
function Choice<T extends string>({
  legend,
  name,
  options,
  value,
  onChange,
  disabled = false,
}: {
  legend: string;
  name: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset disabled={disabled} className="min-w-0 space-y-2 disabled:opacity-50">
      <legend className="text-sm font-medium text-foreground">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <label
            key={option.value}
            className="flex cursor-pointer items-center gap-2 rounded-full border border-border bg-white/[0.03] px-3 py-1.5 text-sm text-muted transition-colors has-[:checked]:border-accent has-[:checked]:bg-accent/10 has-[:checked]:text-foreground has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent"
            title={option.hint}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {/* The check mark keeps the state readable without relying on colour alone. */}
            {value === option.value ? (
              <span aria-hidden="true" className="text-accent">
                ✓
              </span>
            ) : null}
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * A schematic of the chosen layout and caption placement. It is a guide only — the rendered
 * short is produced by FFmpeg on the server and is the authoritative result.
 */
function LayoutGuide({ layout, captions, position }: { layout: Layout; captions: boolean; position: CaptionPosition }) {
  const frame =
    layout === "center_crop" ? (
      <div className="absolute inset-0 bg-accent/40" />
    ) : (
      <>
        <div className={`absolute inset-0 ${layout === "blur_background" ? "bg-accent/20 blur-[2px]" : "bg-zinc-900"}`} />
        <div className="absolute inset-x-0 top-1/2 h-[28%] -translate-y-1/2 bg-accent/50" />
      </>
    );
  const captionPosition = position === "top" ? "top-[14%]" : position === "center" ? "top-1/2 -translate-y-1/2" : "bottom-[17%]";
  return (
    <figure className="flex flex-col items-center gap-2">
      <div
        aria-hidden="true"
        className="relative aspect-[9/16] w-24 overflow-hidden rounded-md border border-border bg-black"
      >
        {frame}
        {captions ? (
          <div className={`absolute inset-x-2 ${captionPosition} h-2 rounded-sm bg-white/90`} />
        ) : null}
      </div>
      <figcaption className="max-w-28 text-center text-[11px] leading-tight text-muted">
        Layout guide — not the rendered result
      </figcaption>
    </figure>
  );
}

type Props = {
  onSubmit: (request: EditRequest) => Promise<ClipEdit>;
  footer?: ReactNode;
};

/** Edit settings for a 9:16 short. Submitting renders on the server; nothing is faked here. */
export function ShortFormEditor({ onSubmit, footer }: Props) {
  const id = useId();
  const [layout, setLayout] = useState<Layout>("blur_background");
  const [captions, setCaptions] = useState(true);
  const [style, setStyle] = useState<CaptionStyle>("bold");
  const [position, setPosition] = useState<CaptionPosition>("bottom");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (busy) return; // double clicks never send a second request (the API is idempotent anyway)
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        aspect_ratio: "9:16",
        layout,
        captions_enabled: captions,
        ...(captions ? { caption_style: style, caption_position: position } : {}),
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="space-y-4"
      aria-label="Short-form edit settings"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <p className="text-xs font-medium tracking-wide text-muted uppercase">Edit settings · 9:16 · 1080 × 1920</p>
      <div className="flex flex-col gap-5 sm:flex-row">
        <div className="min-w-0 flex-1 space-y-4">
          <Choice legend="Layout" name={`${id}-layout`} options={LAYOUT_OPTIONS} value={layout} onChange={setLayout} />
          <label className="flex items-center gap-2 text-sm font-medium text-foreground">
            <input
              type="checkbox"
              checked={captions}
              onChange={(event) => setCaptions(event.target.checked)}
              className="size-4 accent-[var(--accent)]"
            />
            Burn in captions from the transcript
          </label>
          <Choice
            legend="Caption style"
            name={`${id}-style`}
            options={STYLE_OPTIONS}
            value={style}
            onChange={setStyle}
            disabled={!captions}
          />
          <Choice
            legend="Caption position"
            name={`${id}-position`}
            options={POSITION_OPTIONS}
            value={position}
            onChange={setPosition}
            disabled={!captions}
          />
        </div>
        <LayoutGuide layout={layout} captions={captions} position={position} />
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted">
          Captions use the transcript&apos;s words and phrase timing. The source clip is kept unchanged.
        </p>
        <Button type="submit" disabled={busy}>
          {busy ? "Starting…" : "Render short"}
        </Button>
      </div>
      <FormError>{error}</FormError>
      {footer}
    </form>
  );
}
