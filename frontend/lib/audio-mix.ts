/**
 * The edit's audio section, as the API accepts it, plus the pure timing rules the editor's
 * preview shares with the renderer (see backend `app/services/audio_mix`).
 *
 * Levels are in dB, the canonical unit; times are seconds of the edited short. Normalization
 * mirrors the server's, so an unchanged section is "no section" and equivalent settings match
 * an existing version.
 */

export type DuckingStrength = "off" | "light" | "medium" | "strong";

export type MusicRequest = {
  asset_id: string;
  gain_db: number;
  source_start_seconds: number;
  loop: boolean;
  fade_in_seconds: number;
  fade_out_seconds: number;
  ducking: DuckingStrength;
};

export type SfxCueRequest = { asset_id: string; at_seconds: number; gain_db: number };

export type AudioRequest = {
  source_gain_db: number;
  normalize: boolean;
  music: MusicRequest | null;
  sfx: SfxCueRequest[];
};

export const SOURCE_GAIN_DB = { min: -24, max: 6 } as const;
export const MUSIC_GAIN_DB = { min: -40, max: 0 } as const;
export const SFX_GAIN_DB = { min: -30, max: 6 } as const;
export const MAX_FADE_SECONDS = 10;
export const MAX_SFX_CUES = 12;

export const DEFAULT_MUSIC: Omit<MusicRequest, "asset_id"> = {
  gain_db: -16,
  source_start_seconds: 0,
  loop: true,
  fade_in_seconds: 0.5,
  fade_out_seconds: 1,
  ducking: "medium",
};
export const DEFAULT_SFX_GAIN_DB = -6;

export const DUCKING_LABELS: Record<Exclude<DuckingStrength, "off">, string> = {
  light: "Light",
  medium: "Medium",
  strong: "Strong",
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const round = (value: number, decimals: number) => {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor + 0; // + 0 turns -0 into 0
};
const gain = (value: number, limits: { min: number; max: number }) => round(clamp(value, limits.min, limits.max), 1);
const seconds = (value: number, max = Infinity) => round(clamp(value, 0, max), 2);

/** The server's normalization: rounded, clamped, cues by time; null when nothing changes. */
export function normalizeAudio(audio: AudioRequest | null | undefined): AudioRequest | null {
  if (!audio) return null;
  const music = audio.music
    ? {
        asset_id: audio.music.asset_id,
        gain_db: gain(audio.music.gain_db, MUSIC_GAIN_DB),
        source_start_seconds: seconds(audio.music.source_start_seconds),
        loop: audio.music.loop,
        fade_in_seconds: seconds(audio.music.fade_in_seconds, MAX_FADE_SECONDS),
        fade_out_seconds: seconds(audio.music.fade_out_seconds, MAX_FADE_SECONDS),
        ducking: audio.music.ducking,
      }
    : null;
  const sfx = audio.sfx
    .slice(0, MAX_SFX_CUES)
    .map((cue) => ({ asset_id: cue.asset_id, at_seconds: seconds(cue.at_seconds), gain_db: gain(cue.gain_db, SFX_GAIN_DB) }))
    .sort((a, b) => a.at_seconds - b.at_seconds || a.asset_id.localeCompare(b.asset_id) || a.gain_db - b.gain_db);
  const normalized = { source_gain_db: gain(audio.source_gain_db, SOURCE_GAIN_DB), normalize: audio.normalize, music, sfx };
  if (!music && sfx.length === 0 && normalized.source_gain_db === 0 && !normalized.normalize) return null;
  return normalized;
}

/** The audio section of a stored edit configuration, in request form (or null). */
export function audioFromConfiguration(configuration: Record<string, unknown> | null | undefined): AudioRequest | null {
  const audio = configuration?.audio as (AudioRequest & { version?: string; loudness?: string }) | undefined;
  if (!audio || typeof audio !== "object") return null;
  return normalizeAudio({
    source_gain_db: audio.source_gain_db,
    normalize: audio.normalize,
    music: audio.music ?? null,
    sfx: audio.sfx ?? [],
  });
}

/** Whether two audio sections render the same (after normalization). */
export function sameAudio(a: AudioRequest | null | undefined, b: AudioRequest | null | undefined) {
  return JSON.stringify(normalizeAudio(a)) === JSON.stringify(normalizeAudio(b));
}

/** dB → linear amplitude (0 dB = 1). */
export const dbToGain = (db: number) => 10 ** (db / 20);

export const formatDb = (db: number) => (db === 0 ? "0 dB" : `${db > 0 ? "+" : "−"}${Math.abs(round(db, 1))} dB`);

/** "1:05.5" style times for the editor. */
export function formatClock(value: number) {
  const safe = Math.max(0, value);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

export type MusicTimeline = { plays: number; needsLoop: boolean; fadeIn: number; fadeOut: number };

/** Where music plays in the short and the fades actually applied (as the renderer decides). */
export function musicTimeline(music: Omit<MusicRequest, "asset_id">, trackSeconds: number, duration: number): MusicTimeline {
  const remaining = Math.max(0, trackSeconds - music.source_start_seconds);
  const needsLoop = music.loop && remaining < duration;
  const plays = needsLoop ? duration : Math.min(duration, remaining);
  let fadeIn = music.fade_in_seconds;
  let fadeOut = music.fade_out_seconds;
  if (fadeIn + fadeOut > plays && plays > 0) {
    const scale = plays / (fadeIn + fadeOut);
    fadeIn *= scale;
    fadeOut *= scale;
  }
  return { plays, needsLoop, fadeIn: Math.min(fadeIn, plays), fadeOut: Math.min(fadeOut, plays) };
}

/** The track position heard at short time `t`, or null when no music plays then. The first
 * pass starts at the chosen point; a loop restarts the track from its beginning. */
export function musicPositionAt(t: number, music: Omit<MusicRequest, "asset_id">, trackSeconds: number, duration: number) {
  const timeline = musicTimeline(music, trackSeconds, duration);
  if (t < 0 || t >= timeline.plays || trackSeconds <= 0) return null;
  const position = music.source_start_seconds + t;
  if (position < trackSeconds) return position;
  return (position - trackSeconds) % trackSeconds;
}

/** Linear music level at short time `t`: the gain with the fades applied (no ducking). */
export function musicLevelAt(t: number, music: Omit<MusicRequest, "asset_id">, trackSeconds: number, duration: number) {
  const timeline = musicTimeline(music, trackSeconds, duration);
  if (t < 0 || t >= timeline.plays) return 0;
  let envelope = 1;
  if (timeline.fadeIn > 0 && t < timeline.fadeIn) envelope = t / timeline.fadeIn;
  const outStart = timeline.plays - timeline.fadeOut;
  if (timeline.fadeOut > 0 && t > outStart) envelope = Math.min(envelope, (timeline.plays - t) / timeline.fadeOut);
  return Math.min(1, dbToGain(music.gain_db) * Math.max(0, envelope));
}

/** Cues whose start was crossed during forward playback from `previous` to `now`. Seeks
 * (backwards, or jumps further than `maxStep`) never fire cues: the preview re-arms instead. */
export function crossedCues<T extends { at_seconds: number }>(cues: readonly T[], previous: number, now: number, maxStep = 0.5): T[] {
  if (now <= previous || now - previous > maxStep) return [];
  return cues.filter((cue) => cue.at_seconds > previous && cue.at_seconds <= now);
}

/** "Music", "Music · 2 sound effects", "1 sound effect" or "Original audio −3 dB" (null: untouched). */
export function audioSummary(audio: AudioRequest | null | undefined): string | null {
  const normalized = normalizeAudio(audio);
  if (!normalized) return null;
  const parts: string[] = [];
  if (normalized.music) parts.push("Music");
  if (normalized.sfx.length) parts.push(`${normalized.sfx.length} sound effect${normalized.sfx.length === 1 ? "" : "s"}`);
  if (!parts.length) parts.push(normalized.source_gain_db === 0 ? "Normalized audio" : `Original audio ${formatDb(normalized.source_gain_db)}`);
  return parts.join(" · ");
}
