"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { Info, Music2, Pause, Play, Plus, Trash2, Upload, Volume2, Waves } from "lucide-react";
import { AudioTimeline, heardPeaks, Waveform } from "@/components/app/editor/audio-timeline";
import { ControlGroup, InlineCheck, OptionCard } from "@/components/app/editor/controls";
import { InlineAlert } from "@/components/ui/inline-alert";
import { ProgressBar } from "@/components/ui/progress";
import { selectClasses } from "@/components/ui/select-styles";
import { ApiError } from "@/lib/api";
import {
  DEFAULT_MUSIC,
  DEFAULT_SFX_GAIN_DB,
  DUCKING_LABELS,
  formatClock,
  formatDb,
  MAX_SFX_CUES,
  MUSIC_GAIN_DB,
  musicTimeline,
  SFX_GAIN_DB,
  SOURCE_GAIN_DB,
  type AudioRequest,
  type DuckingStrength,
} from "@/lib/audio-mix";
import {
  AUDIO_ACCEPT,
  audioContentUrl,
  formatAudioDuration,
  uploadAudio,
  type AudioAsset,
  type AudioKind,
  type AudioUploadLimits,
} from "@/lib/audio";
import { useAssetListening } from "@/lib/use-audio-preview";

const FADE_CHOICES = [0, 0.5, 1, 2, 3, 5];
// Measured music dips with a typical speech level (see docs/audio-sound-design.md).
const DUCKING_DEPTH: Record<Exclude<DuckingStrength, "off">, string> = { light: "about 7 dB", medium: "about 13 dB", strong: "about 19 dB" };

const inputClasses =
  "h-9 rounded-lg border border-border bg-surface-2 px-2.5 text-sm text-foreground tabular focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-accent/40";

function SwitchRow({ label, hint, checked, onChange, icon }: { label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; icon?: ReactNode }) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p id={`${id}-label`} className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {icon}
          {label}
        </p>
        <p id={`${id}-hint`} className="text-xs text-subtle">
          {hint}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-hint`}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          checked ? "border-accent bg-accent" : "border-border-strong bg-surface-3"
        }`}
      >
        <span className="sr-only">{checked ? "On" : "Off"}</span>
        <span
          aria-hidden="true"
          className={`inline-block size-[18px] rounded-full bg-white shadow transition-transform duration-150 ${checked ? "translate-x-[22px]" : "translate-x-[2px]"}`}
        />
      </button>
    </div>
  );
}

function LevelSlider({ label, value, min, max, step, onChange, hint }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; hint?: string }) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="flex items-baseline justify-between text-sm font-medium text-foreground">
        {label}
        <span className="tabular text-xs text-subtle">{formatDb(value)}</span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={formatDb(value)}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="h-6 w-full cursor-pointer accent-[var(--accent)]"
      />
      {hint ? (
        <p id={`${id}-hint`} className="text-[11px] text-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function UploadButton({ kind, projectId, onUploaded }: { kind: AudioKind; projectId: string; onUploaded: (asset: AudioAsset) => void }) {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const label = kind === "music" ? "Upload music" : "Upload sound effect";
  async function upload(file: File | undefined) {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      onUploaded(await uploadAudio(projectId, file, kind, setProgress));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The upload failed. Try again.");
    } finally {
      setProgress(null);
    }
  }
  return (
    <div className="space-y-2">
      <label
        className={`inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-border-strong bg-surface-2 px-3 text-[13px] font-medium text-foreground transition-colors hover:bg-surface-3 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
          progress !== null ? "pointer-events-none opacity-60" : ""
        }`}
      >
        <Upload aria-hidden="true" className="size-3.5" />
        {progress !== null ? "Uploading…" : label}
        <input
          type="file"
          accept={AUDIO_ACCEPT}
          className="sr-only"
          disabled={progress !== null}
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </label>
      {progress !== null ? <ProgressBar value={progress} label={`${label} progress`} /> : null}
      {error ? <InlineAlert title="That file couldn't be added">{error}</InlineAlert> : null}
    </div>
  );
}

export function AudioPanel({
  projectId,
  value,
  onChange,
  assets,
  waveforms,
  limits,
  duration,
  video,
  onUploaded,
}: {
  projectId: string;
  value: AudioRequest;
  onChange: (next: AudioRequest) => void;
  assets: AudioAsset[] | null;
  waveforms: Record<string, number[]>;
  limits: AudioUploadLimits | null;
  duration: number;
  video: HTMLVideoElement | null;
  onUploaded: (asset: AudioAsset) => void;
}) {
  const id = useId();
  const listening = useAssetListening();
  const [playing, setPlaying] = useState<string | null>(null);
  useEffect(() => {
    // One sound at a time: playing the preview stops a "Listen" player.
    if (!video) return;
    const stop = () => {
      listening.stop();
      setPlaying(null);
    };
    video.addEventListener("play", stop);
    return () => video.removeEventListener("play", stop);
  }, [video, listening]);
  const music = assets?.filter((a) => a.kind === "music") ?? [];
  const effects = assets?.filter((a) => a.kind === "sfx") ?? [];
  const chosen = value.music ? (assets?.find((a) => a.id === value.music!.asset_id) ?? null) : null;
  const byId = new Map(assets?.map((a) => [a.id, a]) ?? []);

  const set = (patch: Partial<AudioRequest>) => onChange({ ...value, ...patch });
  const setMusic = (patch: Partial<NonNullable<AudioRequest["music"]>>) => value.music && set({ music: { ...value.music, ...patch } });
  const setCue = (index: number, patch: Partial<AudioRequest["sfx"][number]>) =>
    set({ sfx: value.sfx.map((cue, i) => (i === index ? { ...cue, ...patch } : cue)) });

  function listen(asset: AudioAsset) {
    if (playing === asset.id) {
      listening.stop();
      setPlaying(null);
      return;
    }
    video?.pause();
    setPlaying(asset.id);
    listening.play(audioContentUrl(projectId, asset.id), () => setPlaying(null));
  }

  const timeline = value.music && chosen ? musicTimeline(value.music, chosen.duration_seconds, duration) : null;
  const musicSpan = (() => {
    if (!value.music || !chosen || !timeline) return null;
    const start = value.music.source_start_seconds;
    if (timeline.needsLoop) return `Plays from ${formatClock(start)}, then repeats from the start to fill the short`;
    if (timeline.plays < duration) return `Plays ${formatClock(start)}–${formatClock(start + timeline.plays)} of the track, then ends at ${formatClock(timeline.plays)}`;
    return `Plays ${formatClock(start)}–${formatClock(start + timeline.plays)} of the track`;
  })();
  const ducking = value.music?.ducking ?? "off";
  const musicPeaks = value.music && chosen && waveforms[chosen.id] ? heardPeaks(waveforms[chosen.id], value.music, chosen.duration_seconds, duration) : null;
  const effectLimitHint = limits ? `Effects up to ${limits.sfx_max_duration_seconds} s` : undefined;

  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-5">
      <div className="space-y-1">
        <h3 id={`${id}-heading`} className="flex items-center gap-1.5 text-[15px] font-semibold text-foreground">
          <Volume2 aria-hidden="true" className="size-4 text-accent-soft" />
          Audio
        </h3>
        <p className="flex items-start gap-1.5 text-xs text-subtle">
          <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          Upload audio you own or have permission to use. PeakSift doesn&apos;t provide a music library.
        </p>
      </div>

      <LevelSlider
        label="Original audio"
        value={value.source_gain_db}
        min={SOURCE_GAIN_DB.min}
        max={SOURCE_GAIN_DB.max}
        step={0.5}
        onChange={(v) => set({ source_gain_db: v })}
        hint={value.source_gain_db > 0 ? "Boosts are heard in the render; the preview plays at most the original level." : "The clip's own sound. 0 dB keeps it as recorded."}
      />

      <ControlGroup legend="Background music" hint={chosen ? formatAudioDuration(chosen.duration_seconds) : undefined}>
        <div className="space-y-2">
          <OptionCard name={`${id}-music`} value="none" label="No music" checked={!value.music} onChange={() => set({ music: null })} className="flex-row items-center justify-between px-3 py-2.5" badge={false}>
            <span className="text-[13px] font-medium text-foreground">No music</span>
            <InlineCheck on={!value.music} />
          </OptionCard>
          {music.map((asset) => {
            const on = value.music?.asset_id === asset.id;
            return (
              <div key={asset.id} className="flex items-stretch gap-2">
                <OptionCard
                  name={`${id}-music`}
                  value={asset.id}
                  label={`${asset.display_name}, ${formatAudioDuration(asset.duration_seconds)}`}
                  checked={on}
                  onChange={() => set({ music: { asset_id: asset.id, ...DEFAULT_MUSIC, ...(value.music ? { gain_db: value.music.gain_db, ducking: value.music.ducking } : {}) } })}
                  className="min-w-0 flex-1 flex-row items-center gap-3 px-3 py-2"
                  badge={false}
                >
                  <Music2 aria-hidden="true" className="size-4 shrink-0 text-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-foreground">{asset.display_name}</span>
                    <span className="tabular block text-[11px] text-subtle">Music · {formatAudioDuration(asset.duration_seconds)}</span>
                  </span>
                  <span className="hidden h-6 w-20 shrink-0 text-muted min-[400px]:block">{waveforms[asset.id] ? <Waveform peaks={waveforms[asset.id]} /> : null}</span>
                  <InlineCheck on={on} />
                </OptionCard>
                <button
                  type="button"
                  onClick={() => listen(asset)}
                  aria-label={`${playing === asset.id ? "Stop" : "Listen to"} ${asset.display_name}`}
                  aria-pressed={playing === asset.id}
                  className="inline-flex w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-surface-2 text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {playing === asset.id ? <Pause aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
                </button>
              </div>
            );
          })}
          {assets === null ? <p className="text-xs text-subtle">Loading your audio…</p> : null}
        </div>
        <UploadButton kind="music" projectId={projectId} onUploaded={onUploaded} />
      </ControlGroup>

      {value.music && chosen ? (
        <div className="animate-fade-in space-y-4 rounded-xl border border-border bg-surface-2/50 p-3.5">
          <LevelSlider label="Music volume" value={value.music.gain_db} min={MUSIC_GAIN_DB.min} max={MUSIC_GAIN_DB.max} step={1} onChange={(v) => setMusic({ gain_db: v })} />
          <div className="space-y-1.5">
            <label htmlFor={`${id}-start`} className="flex items-baseline justify-between text-sm font-medium text-foreground">
              Start from
              <span className="tabular text-xs text-subtle">of {formatAudioDuration(chosen.duration_seconds)}</span>
            </label>
            <div className="flex items-center gap-2">
              <input
                id={`${id}-start`}
                type="number"
                inputMode="decimal"
                min={0}
                max={Math.max(0, chosen.duration_seconds - 0.1)}
                step={0.5}
                value={value.music.source_start_seconds}
                onChange={(e) => setMusic({ source_start_seconds: Math.min(Math.max(0, Number(e.target.value) || 0), Math.max(0, chosen.duration_seconds - 0.1)) })}
                aria-describedby={`${id}-start-hint`}
                className={`${inputClasses} w-24`}
              />
              <span className="text-xs text-subtle">seconds</span>
            </div>
            <div className="relative h-7 text-muted">
              {waveforms[chosen.id] ? <Waveform peaks={waveforms[chosen.id]} /> : null}
              <span
                aria-hidden="true"
                className="absolute inset-y-0 w-0.5 bg-accent"
                style={{ left: `${(value.music.source_start_seconds / chosen.duration_seconds) * 100}%` }}
              />
            </div>
            <p id={`${id}-start-hint`} className="text-[11px] text-subtle">
              {musicSpan}
            </p>
          </div>
          <SwitchRow label="Loop to fit" hint="Repeat the track if it ends before the short" checked={value.music.loop} onChange={(v) => setMusic({ loop: v })} />
          <div className="grid grid-cols-2 gap-3">
            {(["fade_in_seconds", "fade_out_seconds"] as const).map((key) => (
              <label key={key} className="block space-y-1.5">
                <span className="text-sm font-medium text-foreground">{key === "fade_in_seconds" ? "Fade in" : "Fade out"}</span>
                <select value={value.music![key]} onChange={(e) => setMusic({ [key]: Number(e.target.value) })} className={selectClasses}>
                  {FADE_CHOICES.map((s) => (
                    <option key={s} value={s}>
                      {s === 0 ? "None" : `${s} s`}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <div className="space-y-2.5">
            <SwitchRow
              icon={<Waves aria-hidden="true" className="size-3.5 text-accent-soft" />}
              label="Automatic ducking"
              hint="Lower the music while the clip's own audio plays"
              checked={ducking !== "off"}
              onChange={(on) => setMusic({ ducking: on ? "medium" : "off" })}
            />
            {ducking !== "off" ? (
              <div className="animate-fade-in space-y-2">
                <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Ducking strength">
                  {(Object.keys(DUCKING_LABELS) as (keyof typeof DUCKING_LABELS)[]).map((strength) => (
                    <OptionCard
                      key={strength}
                      name={`${id}-ducking`}
                      value={strength}
                      label={`${DUCKING_LABELS[strength]} ducking`}
                      checked={ducking === strength}
                      onChange={() => setMusic({ ducking: strength })}
                      className="flex-row items-center justify-center gap-1.5 px-2 py-2"
                      badge={false}
                    >
                      <span className="text-[13px] font-medium text-foreground">{DUCKING_LABELS[strength]}</span>
                      <InlineCheck on={ducking === strength} />
                    </OptionCard>
                  ))}
                </div>
                <p role="status" className="text-[11px] text-subtle">
                  <span className="font-medium text-muted">Ducking: {DUCKING_LABELS[ducking]}.</span> Music dips by {DUCKING_DEPTH[ducking]} while the clip&apos;s audio
                  is active (it follows overall loudness, not a separated voice).
                </p>
              </div>
            ) : (
              <p role="status" className="text-[11px] text-subtle">
                <span className="font-medium text-muted">Ducking off.</span> Music stays at its volume.
              </p>
            )}
          </div>
        </div>
      ) : null}

      <ControlGroup legend="Sound effects" hint={`${value.sfx.length}/${MAX_SFX_CUES}`}>
        {value.sfx.length ? (
          <ol className="space-y-2">
            {value.sfx.map((cue, index) => {
              const asset = byId.get(cue.asset_id);
              return (
                <li key={index} className="space-y-2 rounded-xl border border-border bg-surface-2/50 p-3">
                  <div className="flex items-center gap-2">
                    <span aria-hidden="true" className="tabular flex size-6 shrink-0 items-center justify-center rounded-md border border-emerald-300/60 bg-emerald-400/15 text-[11px] font-semibold text-emerald-100">
                      {index + 1}
                    </span>
                    <label className="min-w-0 flex-1">
                      <span className="sr-only">Sound effect {index + 1}</span>
                      <select value={cue.asset_id} onChange={(e) => setCue(index, { asset_id: e.target.value })} className={`${selectClasses} h-9`}>
                        {effects.map((effect) => (
                          <option key={effect.id} value={effect.id}>
                            {effect.display_name}
                          </option>
                        ))}
                        {!asset ? <option value={cue.asset_id}>Unavailable effect</option> : null}
                      </select>
                    </label>
                    <button
                      type="button"
                      onClick={() => set({ sfx: value.sfx.filter((_, i) => i !== index) })}
                      aria-label={`Remove sound effect ${index + 1}`}
                      className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-3 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      <Trash2 aria-hidden="true" className="size-4" />
                    </button>
                  </div>
                  <div className="grid grid-cols-1 items-center gap-3 min-[400px]:grid-cols-[auto_1fr]">
                    <label className="flex items-center gap-1.5 text-xs text-muted">
                      At
                      <input
                        type="number"
                        inputMode="decimal"
                        min={0}
                        max={duration}
                        step={0.1}
                        value={cue.at_seconds}
                        onChange={(e) => setCue(index, { at_seconds: Math.min(Math.max(0, Number(e.target.value) || 0), duration) })}
                        aria-label={`Sound effect ${index + 1} time in seconds`}
                        className={`${inputClasses} w-20`}
                      />
                      s
                    </label>
                    <LevelSlider label="Volume" value={cue.gain_db} min={SFX_GAIN_DB.min} max={SFX_GAIN_DB.max} step={1} onChange={(v) => setCue(index, { gain_db: v })} />
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-xs text-subtle">No sound effects. Add one at the preview&apos;s current time.</p>
        )}
        <div className="flex flex-wrap items-start gap-2">
          <button
            type="button"
            disabled={!effects.length || value.sfx.length >= MAX_SFX_CUES}
            onClick={() =>
              set({
                sfx: [
                  ...value.sfx,
                  { asset_id: effects[0].id, at_seconds: Math.round(Math.min(duration, video?.currentTime ?? 0) * 10) / 10, gain_db: DEFAULT_SFX_GAIN_DB },
                ],
              })
            }
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border-strong bg-surface-2 px-3 text-[13px] font-medium text-foreground transition-colors hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus aria-hidden="true" className="size-3.5" />
            Add sound effect
          </button>
          <UploadButton kind="sfx" projectId={projectId} onUploaded={onUploaded} />
        </div>
        {!effects.length ? <p className="text-[11px] text-subtle">Upload a short sound to place it. {effectLimitHint}</p> : null}
      </ControlGroup>

      {value.music || value.sfx.length ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">Audio timeline</p>
          <AudioTimeline
            duration={duration}
            video={video}
            musicPeaks={musicPeaks}
            cues={value.sfx.map((cue, index) => ({ key: `${index}`, label: byId.get(cue.asset_id)?.display_name ?? "Sound effect", at: cue.at_seconds }))}
            onMoveCue={(index, at) => setCue(index, { at_seconds: Math.min(Math.max(0, at), duration) })}
          />
          <p className="text-[11px] text-subtle">Drag a numbered marker or use the arrow keys to move an effect. Click the strip to jump the preview.</p>
        </div>
      ) : null}

      <SwitchRow
        label="Normalize final mix"
        hint="Even loudness for social video (PeakSift target −14 LUFS) and no clipping"
        checked={value.normalize}
        onChange={(v) => set({ normalize: v })}
      />
      <p className="text-[11px] text-subtle">
        The preview plays your music and effects with the video. Ducking and loudness normalization are applied in the render, which is the final
        result.
      </p>
    </section>
  );
}
