"use client";

import { AudioLines, CheckCircle2, Sparkles, Type } from "lucide-react";
import { useId } from "react";
import { PresetSample } from "@/components/app/editor/caption-layer";
import { ControlGroup, InlineCheck, OptionCard } from "@/components/app/editor/controls";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { WorkingState } from "@/components/ui/progress";
import {
  isTrackActive,
  timingErrorCopy,
  timingStageLabel,
  type CaptionStyles,
  type CaptionTiming,
  type CaptionTrack,
  type DynamicPreset,
  type HookPosition,
  type HookStyle,
} from "@/lib/captions";

const PRESET_HINTS: Record<DynamicPreset, string> = {
  focus: "Large and clean, spoken word in yellow",
  punch: "Bold uppercase, spoken word in green",
  minimal: "Small and restrained, subtle emphasis",
  boxed: "White on a dark box, spoken word in yellow",
};

/** Dynamic caption presets as visual cards (real radios): each shows its emphasised word. */
export function PresetCards({
  spec,
  value,
  onChange,
  name,
  disabled,
}: {
  spec: CaptionStyles;
  value: DynamicPreset;
  onChange: (v: DynamicPreset) => void;
  name: string;
  disabled: boolean;
}) {
  return (
    <ControlGroup legend="Caption style" disabled={disabled}>
      <div className="grid grid-cols-2 gap-2">
        {spec.presets.map((preset) => (
          <OptionCard
            key={preset.name}
            name={name}
            value={preset.name}
            label={`${preset.label}: ${PRESET_HINTS[preset.name]}`}
            checked={value === preset.name}
            onChange={() => onChange(preset.name)}
            className="overflow-hidden"
            badge={false}
          >
            <span
              aria-hidden="true"
              className="flex h-[68px] items-center justify-center bg-[linear-gradient(135deg,#3f3f46,#1f1f23)] px-2"
            >
              <PresetSample spec={spec} preset={preset.name} />
            </span>
            <span className="px-2.5 py-2">
              <span className="flex items-center justify-between gap-1.5 text-small font-medium text-foreground">
                {preset.label}
                <InlineCheck on={value === preset.name} />
              </span>
              <span className="block text-caption leading-snug text-subtle">{PRESET_HINTS[preset.name]}</span>
            </span>
          </OptionCard>
        ))}
      </div>
    </ControlGroup>
  );
}

/**
 * How captions are timed, in plain language. Word synced = real word timestamps from the
 * clip's audio; Phrase timed = transcript phrases, no per-word emphasis. Never switched
 * silently: the creator chooses, and the status says what will be rendered.
 */
export function CaptionTimingPanel({
  timing,
  onTimingChange,
  track,
  phraseAvailable,
  busy,
  error,
  onGenerate,
  onRetry,
}: {
  timing: CaptionTiming;
  onTimingChange: (t: CaptionTiming) => void;
  /** undefined = loading, null = never generated. */
  track: CaptionTrack | null | undefined;
  phraseAvailable: boolean;
  busy: boolean;
  error: string | null;
  onGenerate: () => void;
  onRetry: () => void;
}) {
  const name = useId();
  const running = !!track && isTrackActive(track.status) && !track.is_stale;
  const failed = !!track && (track.status === "failed" || (isTrackActive(track.status) && track.is_stale));
  const ready = track?.status === "completed";

  let status;
  if (timing === "phrase_fallback") {
    status = (
      <p className="flex items-start gap-2 text-xs text-muted">
        <Type aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <span className="font-medium text-foreground">Phrase timed.</span> Captions follow transcript phrases; words are not
          emphasised one by one.
        </span>
      </p>
    );
  } else if (track === undefined) {
    status = <WorkingState label="Checking word timing" />;
  } else if (ready && track.word_count === 0) {
    status = (
      <p className="flex items-start gap-2 text-xs text-muted" role="status">
        <Type aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <span className="font-medium text-foreground">No spoken words found</span> in this clip&apos;s audio, so
          there is nothing to caption.
        </span>
      </p>
    );
  } else if (ready) {
    status = (
      <p className="flex items-center gap-2 text-xs text-muted" role="status">
        <CheckCircle2 aria-hidden="true" className="size-3.5 shrink-0 text-success" />
        <span>
          <span className="font-medium text-foreground">Word synced</span>
          {track.word_count != null
            ? ` · ${track.word_count} ${track.word_count === 1 ? "word" : "words"} timed from the clip's audio`
            : null}
        </span>
      </p>
    );
  } else if (running) {
    status = (
      <WorkingState
        label={`Generating word sync · ${timingStageLabel(track)}`}
        progress={track.status === "queued" ? null : track.progress_percent}
        progressLabel="Word timing progress"
        detail="Runs in the background on the clip's own audio."
      />
    );
  } else if (failed) {
    status = (
      <div className="space-y-2">
        <InlineAlert tone={track.status === "failed" ? "danger" : "warning"} title={track.status === "failed" ? "Word timing failed" : "Word timing stalled"}>
          {track.status === "failed" ? timingErrorCopy(track) : "Word timing stopped responding."}
        </InlineAlert>
        <Button variant="secondary" className="w-full" onClick={onRetry} disabled={busy}>
          {busy ? "Retrying…" : "Retry word sync"}
        </Button>
      </div>
    );
  } else {
    status = (
      <div className="space-y-2.5">
        <p className="text-xs text-muted">
          Time every word from the clip&apos;s audio so the spoken word lights up. Takes a moment in the background.
        </p>
        <Button className="w-full" onClick={onGenerate} disabled={busy}>
          <AudioLines aria-hidden="true" />
          {busy ? "Starting…" : "Generate word sync"}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2.5 rounded-block border border-border bg-surface-2 p-3">
      <fieldset className="grid grid-cols-2 gap-1 rounded-control border border-border bg-surface p-0.5">
        <legend className="sr-only">Caption timing</legend>
        {(
          [
            { value: "aligned_word", label: "Word synced" },
            { value: "phrase_fallback", label: "Phrase timed" },
          ] as const
        ).map((option) => {
          const off = option.value === "phrase_fallback" && !phraseAvailable;
          return (
            <label
              key={option.value}
              className={`flex h-8 items-center justify-center rounded-md text-small font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
                off ? "cursor-not-allowed opacity-40" : "cursor-pointer"
              } ${timing === option.value ? "bg-surface-3 text-foreground shadow-sm" : "text-muted hover:text-foreground"}`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={timing === option.value}
                disabled={off}
                onChange={() => onTimingChange(option.value)}
                className="sr-only"
              />
              {option.label}
            </label>
          );
        })}
      </fieldset>
      {status}
      {error ? <InlineAlert title="Word timing could not start">{error}</InlineAlert> : null}
    </div>
  );
}

/** The optional opening hook: one short line, a style, a bounded duration and a safe position. */
export function HookPanel({
  spec,
  enabled,
  onEnabled,
  text,
  onText,
  style,
  onStyle,
  position,
  onPosition,
  duration,
  onDuration,
  captionPosition,
  emojiOmitted,
}: {
  spec: CaptionStyles;
  enabled: boolean;
  onEnabled: (v: boolean) => void;
  text: string;
  onText: (v: string) => void;
  style: HookStyle;
  onStyle: (v: HookStyle) => void;
  position: HookPosition;
  onPosition: (v: HookPosition) => void;
  duration: number;
  onDuration: (v: number) => void;
  /** Where captions are (null = off): the hook never shares their position. */
  captionPosition: string | null;
  emojiOmitted: boolean;
}) {
  const id = useId();
  const length = [...text.trim()].length;
  const tooLong = length > spec.hook.max_chars;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4 rounded-block border border-border bg-surface-2 px-3.5 py-3">
        <div className="min-w-0">
          <p id={`${id}-label`} className="flex items-center gap-1.5 text-sm font-medium text-foreground">
            <Sparkles aria-hidden="true" className="size-3.5 text-accent-soft" />
            Opening hook
          </p>
          <p id={`${id}-hint`} className="text-xs text-subtle">
            One short line over the first seconds
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-labelledby={`${id}-label`}
          aria-describedby={`${id}-hint`}
          onClick={() => onEnabled(!enabled)}
          className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
            enabled ? "border-accent bg-accent" : "border-border-strong bg-surface-3"
          }`}
        >
          <span className="sr-only">{enabled ? "On" : "Off"}</span>
          <span
            aria-hidden="true"
            className={`inline-block size-[18px] rounded-full bg-white shadow transition-transform duration-150 ${
              enabled ? "translate-x-[22px]" : "translate-x-[2px]"
            }`}
          />
        </button>
      </div>
      {enabled ? (
        <div className="animate-fade-in space-y-3">
          <label className="block space-y-1.5">
            <span className="flex items-baseline justify-between text-sm font-medium text-foreground">
              Hook text
              <span className={`tabular text-xs ${tooLong ? "text-danger" : "text-subtle"}`}>
                {length}/{spec.hook.max_chars}
              </span>
            </span>
            <input
              type="text"
              value={text}
              dir="auto"
              onChange={(e) => onText(e.target.value)}
              placeholder="What this clip is about"
              aria-invalid={tooLong || length === 0}
              aria-describedby={`${id}-text-hint`}
              className="h-10 w-full rounded-control border border-border bg-surface-2 px-3 text-sm text-foreground placeholder:text-subtle focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-accent/40"
            />
            <span id={`${id}-text-hint`} className="block text-caption text-subtle">
              {tooLong
                ? `Keep it to ${spec.hook.max_chars} characters.`
                : length === 0
                  ? "Add a line, or turn the hook off."
                  : emojiOmitted
                    ? "Emoji are left out on this server."
                    : "Shown exactly as typed."}
            </span>
          </label>
          <ControlGroup legend="Hook style">
            <div className="grid grid-cols-3 gap-2">
              {spec.hook.styles.map((look) => (
                <OptionCard
                  key={look.name}
                  name={`${id}-style`}
                  value={look.name}
                  label={look.label}
                  checked={style === look.name}
                  onChange={() => onStyle(look.name)}
                  className="items-center justify-center gap-1.5 px-2 py-2.5"
                  badge={false}
                >
                  <span
                    aria-hidden="true"
                    className="rounded-[3px] px-1.5 py-0.5 text-caption leading-none"
                    style={{
                      fontWeight: look.bold ? 700 : 400,
                      color: look.text,
                      background: look.box ? look.outline_colour : "transparent",
                      textShadow: look.box ? undefined : "0 0 2px #000, 0 0 2px #000",
                    }}
                  >
                    Aa
                  </span>
                  <span className="flex items-center gap-1 text-caption font-medium text-foreground">
                    {look.label}
                    <InlineCheck on={style === look.name} />
                  </span>
                </OptionCard>
              ))}
            </div>
          </ControlGroup>
          <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
            <ControlGroup legend="Position" hint={captionPosition === "top" || captionPosition === "center" ? "Not where captions are" : undefined}>
              <div className="grid grid-cols-2 gap-2">
                {(["top", "center"] as const).map((value) => (
                  <OptionCard
                    key={value}
                    name={`${id}-position`}
                    value={value}
                    label={value === "top" ? "Top" : "Center"}
                    checked={position === value}
                    onChange={() => onPosition(value)}
                    disabled={captionPosition === value}
                    className="flex-row items-center justify-center gap-1.5 px-2 py-2"
                    badge={false}
                  >
                    <span className="text-small font-medium text-foreground">{value === "top" ? "Top" : "Center"}</span>
                    <InlineCheck on={position === value} />
                  </OptionCard>
                ))}
              </div>
            </ControlGroup>
            <label className="block space-y-2">
              <span className="flex items-baseline justify-between text-sm font-medium text-foreground">
                Duration
                <span className="tabular text-xs text-subtle">{duration.toFixed(1)} s</span>
              </span>
              <input
                type="range"
                min={spec.hook.min_seconds}
                max={spec.hook.max_seconds}
                step={0.5}
                value={duration}
                onChange={(e) => onDuration(Number(e.target.value))}
                aria-valuetext={`${duration.toFixed(1)} seconds`}
                className="h-1.5 w-full cursor-pointer accent-[var(--accent)]"
              />
            </label>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** "Show safe area" — a real checkbox; the guide itself is labelled, never colour-only. */
export function SafeAreaToggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-control border border-border bg-surface-2 px-2.5 text-small pointer-coarse:h-11 font-medium text-muted transition-colors hover:text-foreground has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-3.5 accent-[var(--accent)]" />
      Safe area
    </label>
  );
}
