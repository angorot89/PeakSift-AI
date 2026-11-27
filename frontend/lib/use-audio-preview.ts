"use client";

import { useEffect, useMemo, useRef } from "react";
import { crossedCues, dbToGain, musicLevelAt, musicPositionAt, type MusicRequest } from "@/lib/audio-mix";

export type PreviewPlan = {
  duration: number;
  sourceGainDb: number;
  music: { url: string; trackSeconds: number; config: Omit<MusicRequest, "asset_id"> } | null;
  cues: { url: string; at_seconds: number; gain_db: number }[];
};

/** Re-seek the music only when it drifts this far from the video clock (avoids stutter). */
const MAX_DRIFT_SECONDS = 0.25;
/** A crossed cue starts only if playback is still inside its first moments. */
const LATE_CUE_SECONDS = 0.3;

const level = (value: number) => Math.min(1, Math.max(0, value));

/** Media element writes, kept out of hooks (their arguments are treated as immutable). */
export function setMediaVolume(element: HTMLMediaElement, value: number) {
  element.volume = value;
}
export function setMediaTime(element: HTMLMediaElement, seconds: number) {
  element.currentTime = seconds;
}
export function setMediaMuted(element: HTMLMediaElement, muted: boolean) {
  element.muted = muted;
}

function unload(element: HTMLAudioElement) {
  element.pause();
  element.removeAttribute("src");
  element.load();
}

/**
 * Plays an approximate audio preview alongside the editor's preview video.
 *
 * The video is the master clock: the music follows `video.currentTime` (re-seeked when it drifts,
 * looped and faded as the renderer does) and pauses with it; sound effects fire only when forward
 * playback crosses their time — seeking never fires them, it re-arms them. The browser cannot
 * boost the clip above its own level, and ducking and loudness normalization are applied only by
 * the render, which is authoritative. Everything stops on pause, on unmount and when navigating
 * away.
 */
export function useAudioPreview(
  video: HTMLVideoElement | null,
  plan: PreviewPlan | null,
  /** With Tighten: the clip's time on the Short's timeline (music and effects are placed there). */
  toShort?: (t: number) => number,
) {
  const latest = useRef(plan);
  const mapTime = useRef(toShort);
  useEffect(() => {
    mapTime.current = toShort;
  }, [toShort]);
  useEffect(() => {
    latest.current = plan;
  }, [plan]);
  const musicUrl = plan?.music?.url ?? null;
  const cueUrls = plan ? plan.cues.map((cue) => cue.url).join("|") : "";
  const active = plan !== null;

  useEffect(() => {
    if (!video || !active) return;
    const music = musicUrl ? new Audio(musicUrl) : null;
    if (music) music.preload = "auto";
    const effects = (cueUrls ? cueUrls.split("|") : []).map((url) => {
      const element = new Audio(url);
      element.preload = "auto";
      return element;
    });
    const now = () => (mapTime.current ? mapTime.current(video.currentTime) : video.currentTime);
    let last = now();
    let frame = 0;

    const syncLevels = () => {
      const current = latest.current;
      setMediaVolume(video, level(dbToGain(current?.sourceGainDb ?? 0)));
    };
    // Muting the preview mutes everything in it, music and effects included.
    const syncMuted = () => {
      if (music) setMediaMuted(music, video.muted);
      effects.forEach((effect) => setMediaMuted(effect, video.muted));
    };
    const syncMusic = (force: boolean) => {
      const current = latest.current;
      if (!music || !current?.music) return;
      const t = now();
      const { config, trackSeconds } = current.music;
      const position = musicPositionAt(t, config, trackSeconds, current.duration);
      if (position == null || video.paused || video.ended) {
        if (!music.paused) music.pause();
        return;
      }
      music.volume = level(musicLevelAt(t, config, trackSeconds, current.duration));
      if (force || Math.abs(music.currentTime - position) > MAX_DRIFT_SECONDS) music.currentTime = position;
      if (music.paused) void music.play().catch(() => {});
    };
    const stopEffects = () => effects.forEach((effect) => effect.pause());
    const fireCrossed = () => {
      const current = latest.current;
      const t = now();
      if (current && !video.paused) {
        crossedCues(current.cues, last, t).forEach((cue) => {
          const index = current.cues.indexOf(cue);
          const effect = effects[index];
          if (!effect || t - cue.at_seconds > LATE_CUE_SECONDS) return;
          effect.currentTime = Math.max(0, t - cue.at_seconds);
          effect.volume = level(dbToGain(cue.gain_db));
          void effect.play().catch(() => {});
        });
      }
      last = t;
    };
    const tick = () => {
      fireCrossed();
      syncMusic(false);
      syncLevels();
      frame = requestAnimationFrame(tick);
    };

    const onPlay = () => {
      last = now();
      syncLevels();
      syncMusic(true);
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(tick);
    };
    const onPause = () => {
      cancelAnimationFrame(frame);
      music?.pause();
      stopEffects();
    };
    const onSeeking = () => {
      stopEffects(); // a seek never fires (or keeps playing) effects
      last = now();
    };
    const onSeeked = () => {
      last = now();
      syncMusic(true);
    };
    // timeupdate keeps the preview honest when animation frames are throttled (background tab).
    const onTimeUpdate = () => {
      fireCrossed();
      syncMusic(false);
    };

    syncLevels();
    syncMuted();
    video.addEventListener("volumechange", syncMuted);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("ended", onPause);
    video.addEventListener("seeking", onSeeking);
    video.addEventListener("seeked", onSeeked);
    video.addEventListener("timeupdate", onTimeUpdate);
    if (!video.paused) onPlay();
    return () => {
      cancelAnimationFrame(frame);
      video.removeEventListener("volumechange", syncMuted);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("ended", onPause);
      video.removeEventListener("seeking", onSeeking);
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("timeupdate", onTimeUpdate);
      if (music) unload(music);
      effects.forEach(unload);
      setMediaVolume(video, 1);
    };
  }, [video, active, musicUrl, cueUrls]);
}

/** One "listen" player for the asset lists: one sound at a time, stopped on unmount. */
export function useAssetListening() {
  const player = useRef<HTMLAudioElement | null>(null);
  useEffect(
    () => () => {
      if (player.current) unload(player.current);
    },
    [],
  );
  return useMemo(
    () => ({
      play(url: string, onEnded: () => void) {
        if (!player.current) player.current = new Audio();
        const element = player.current;
        element.pause();
        element.src = url;
        element.onended = onEnded;
        void element.play().catch(onEnded);
      },
      stop() {
        player.current?.pause();
      },
    }),
    [],
  );
}
