"use client";

import { Maximize, Minimize, Pause, Play, Volume2, VolumeX } from "lucide-react";
import { useCallback, useContext, useRef, useSyncExternalStore } from "react";
import { ShortTimeContext } from "@/components/app/editor/caption-layer";

/** Playback time, rounded down like a player ("0:07"). */
function clock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const noop = () => () => {};

const MEDIA_EVENTS = ["play", "pause", "ended", "timeupdate", "seeked", "loadedmetadata", "durationchange", "volumechange"];
type MediaState = { playing: boolean; time: number; duration: number; muted: boolean };
const IDLE: MediaState = { playing: false, time: 0, duration: 0, muted: false };

/** The preview video's state, read from the element (it is the single source of truth). */
function useMediaState(video: HTMLVideoElement | null): MediaState {
  const cache = useRef<{ key: string; state: MediaState }>({ key: "", state: IDLE });
  const subscribe = useCallback(
    (notify: () => void) => {
      if (!video) return () => {};
      MEDIA_EVENTS.forEach((name) => video.addEventListener(name, notify));
      return () => MEDIA_EVENTS.forEach((name) => video.removeEventListener(name, notify));
    },
    [video],
  );
  const snapshot = useCallback(() => {
    if (!video) return IDLE;
    const state = {
      playing: !video.paused && !video.ended,
      time: video.currentTime,
      duration: Number.isFinite(video.duration) ? video.duration : 0,
      muted: video.muted,
    };
    const key = `${state.playing}|${state.time}|${state.duration}|${state.muted}`;
    if (key !== cache.current.key) cache.current = { key, state };
    return cache.current.state;
  }, [video]);
  return useSyncExternalStore(subscribe, snapshot, () => IDLE);
}

function useFullscreen(target: HTMLElement | null): boolean {
  const subscribe = useCallback((notify: () => void) => {
    document.addEventListener("fullscreenchange", notify);
    return () => document.removeEventListener("fullscreenchange", notify);
  }, []);
  return useSyncExternalStore(
    subscribe,
    () => !!target && document.fullscreenElement === target,
    () => false,
  );
}

/** Media element writes, kept out of render. */
function seek(video: HTMLVideoElement, seconds: number) {
  video.currentTime = seconds;
}
function setMuted(video: HTMLVideoElement, muted: boolean) {
  video.muted = muted;
}

const controlButton =
  "flex size-9 shrink-0 items-center justify-center rounded-full text-foreground transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40 pointer-coarse:size-11";

/**
 * Play/pause, seek, time, mute and full screen for the editor's live preview. The video element
 * stays the clock (captions, visuals and the audio preview follow it); full screen shows the
 * whole 9:16 frame with its overlays.
 */
export function PreviewControls({
  video,
  fullscreenTarget,
}: {
  video: HTMLVideoElement | null;
  fullscreenTarget: HTMLElement | null;
}) {
  const media = useMediaState(video);
  // With Tighten the bar shows the Short: its length, and where the playhead is in it.
  const map = useContext(ShortTimeContext);
  const { playing, muted } = media;
  const time = map ? map.toShort(media.time) : media.time;
  const duration = map && media.duration ? map.seconds : media.duration;
  const fullscreen = useFullscreen(fullscreenTarget);
  const supported = useSyncExternalStore(noop, () => !!document.fullscreenEnabled, () => false);
  const canFullscreen = supported && !!fullscreenTarget;

  function toggle() {
    if (!video) return;
    if (video.paused || video.ended) void video.play().catch(() => {});
    else video.pause();
  }
  function toggleFullscreen() {
    if (!fullscreenTarget) return;
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void fullscreenTarget.requestFullscreen().catch(() => {});
  }

  return (
    <div className="mx-auto flex w-full max-w-[calc(min(64vh,600px)*0.5625)] min-w-[15rem] lg:max-w-[calc(min(max(100dvh-25rem,22rem),600px)*0.5625)] items-center gap-1.5 [:fullscreen_&]:max-w-[calc((100dvh-5rem)*0.5625)]">
      <button type="button" onClick={toggle} disabled={!video} aria-label={playing ? "Pause preview" : "Play preview"} className={controlButton}>
        {playing ? <Pause aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
      </button>
      <input
        type="range"
        min={0}
        max={duration || 0}
        step={0.05}
        value={Math.min(time, duration || 0)}
        disabled={!video || !duration}
        aria-label="Seek preview"
        aria-valuetext={`${clock(time)} of ${clock(duration)}`}
        onChange={(event) => {
          const value = Number(event.target.value);
          if (video) seek(video, map ? map.toClip(value) : value);
        }}
        className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--accent)] pointer-coarse:h-11"
      />
      <span className="tabular shrink-0 px-1 text-caption text-subtle">
        {clock(time)} / {clock(duration)}
      </span>
      <button
        type="button"
        onClick={() => video && setMuted(video, !muted)}
        disabled={!video}
        aria-label={muted ? "Unmute preview" : "Mute preview"}
        aria-pressed={muted}
        className={controlButton}
      >
        {muted ? <VolumeX aria-hidden="true" className="size-4" /> : <Volume2 aria-hidden="true" className="size-4" />}
      </button>
      {canFullscreen ? (
        <button
          type="button"
          onClick={toggleFullscreen}
          aria-label={fullscreen ? "Exit full screen" : "Full screen preview"}
          className={controlButton}
        >
          {fullscreen ? <Minimize aria-hidden="true" className="size-4" /> : <Maximize aria-hidden="true" className="size-4" />}
        </button>
      ) : null}
    </div>
  );
}
