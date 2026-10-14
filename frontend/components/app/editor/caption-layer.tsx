"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import { parseState, stateAt, type PreviewCue } from "@/lib/caption-timing";
import type { CaptionStyles, DynamicPreset, HookPosition, HookStyle } from "@/lib/captions";

/** The preview's playing video, provided by the stage so overlays follow its clock. */
export const VideoClockContext = createContext<RefObject<HTMLVideoElement | null> | null>(null);

type VideoWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

/** Call `onTime` with the clip time of every presented frame (rVFC, rAF fallback) and on seeks. */
function useClipTime(onTime: (t: number) => void) {
  const video = useContext(VideoClockContext);
  const latest = useRef(onTime);
  useEffect(() => {
    latest.current = onTime;
  }, [onTime]);
  useEffect(() => {
    const element = video?.current as VideoWithFrameCallback | null;
    if (!element) return;
    let handle = 0;
    let raf = 0;
    const read = () => latest.current(element.currentTime || 0);
    if (element.requestVideoFrameCallback) {
      const loop = (_now: number, meta: { mediaTime: number }) => {
        latest.current(meta.mediaTime);
        handle = element.requestVideoFrameCallback!(loop);
      };
      handle = element.requestVideoFrameCallback(loop);
    } else {
      const tick = () => {
        read();
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }
    read();
    element.addEventListener("seeked", read);
    element.addEventListener("timeupdate", read);
    element.addEventListener("loadeddata", read);
    return () => {
      if (handle && element.cancelVideoFrameCallback) element.cancelVideoFrameCallback(handle);
      if (raf) cancelAnimationFrame(raf);
      element.removeEventListener("seeked", read);
      element.removeEventListener("timeupdate", read);
      element.removeEventListener("loadeddata", read);
    };
  }, [video]);
}

// Output-frame pixels → container units of the 9:16 frame (which declares container-type: size).
const ch = (px: number, height: number) => `${((px / height) * 100).toFixed(3)}cqh`;
const cw = (px: number, width: number) => `${((px / width) * 100).toFixed(3)}cqw`;

function rgba(hex: string, opacity = 1) {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255} / ${opacity})`;
}

function outline(width: string, colour: string, shadow: string | null) {
  const steps = [
    [1, 0], [-1, 0], [0, 1], [0, -1], [0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7],
  ];
  const ring = steps.map(([x, y]) => `calc(${x} * ${width}) calc(${y} * ${width}) 0 ${colour}`);
  return [...ring, ...(shadow ? [`${shadow} ${shadow} 0 rgb(0 0 0 / 0.5)`] : [])].join(", ");
}

type TextLook = {
  size: number;
  bold: boolean;
  text: string;
  outline_colour: string;
  outline: number;
  shadow: number;
  box: boolean;
  box_alpha: number;
};

// Noto Sans' CSS content area (hhea ascent + descent): what an inline background covers.
const CONTENT_EM = 1.362;

/** CSS for libass-styled text: same size (em = size × em_per_size), weight, outline or box. */
function textCss(look: TextLook, spec: CaptionStyles): CSSProperties {
  const h = spec.output_height;
  const css: CSSProperties = {
    fontSize: ch(look.size * spec.font.em_per_size, h),
    lineHeight: 1 / spec.font.em_per_size, // libass line height is the font size
    fontWeight: look.bold ? 700 : 400,
    color: look.text,
    fontFamily: "var(--font-caption), 'Noto Sans', sans-serif",
    whiteSpace: "nowrap", // the renderer already chose the lines
  };
  if (look.box) {
    css.backgroundColor = rgba(look.outline_colour, (255 - look.box_alpha) / 255);
    // libass boxes the whole line (the font size) plus the outline on every side.
    const vertical = (look.size * (1 - spec.font.em_per_size * CONTENT_EM)) / 2 + look.outline;
    css.padding = `${ch(vertical, h)} ${ch(look.outline, h)}`;
    css.boxDecorationBreak = "clone";
    css.WebkitBoxDecorationBreak = "clone";
  } else {
    css.textShadow = outline(ch(look.outline, h), look.outline_colour, look.shadow ? ch(look.shadow, h) : null);
  }
  return css;
}

// libass pads a box by the outline; box styles sit that much further in so the box stays inside.
const boxInset = (look: TextLook, alignment: number) => (look.box && alignment !== 5 ? Math.round(look.outline) : 0);

function placementCss(alignment: number, marginV: number, marginH: number, spec: CaptionStyles): CSSProperties {
  const css: CSSProperties = {
    left: cw(marginH, spec.output_width),
    right: cw(marginH, spec.output_width),
  };
  if (alignment === 8) css.top = ch(marginV, spec.output_height);
  else if (alignment === 2) css.bottom = ch(marginV, spec.output_height);
  else {
    css.top = "50%";
    css.transform = "translateY(-50%)";
  }
  return css;
}

export type HookPreview = { text: string; style: HookStyle; position: HookPosition; duration: number };

/**
 * The dynamic captions and the hook, drawn over the 9:16 preview in output-frame coordinates
 * from the renderer's own numbers and cues. Captions never move with the crop. Re-renders only
 * when what is visible changes (cue, active word, hook on/off), not on every frame.
 */
export function CaptionLayer({
  spec,
  preset,
  position,
  cues,
  hook,
  showSafeArea,
}: {
  spec: CaptionStyles;
  preset: DynamicPreset | null;
  position: "top" | "center" | "bottom";
  cues: PreviewCue[] | null;
  hook: HookPreview | null;
  showSafeArea: boolean;
}) {
  const [state, setState] = useState("");
  const [hookOn, setHookOn] = useState(false);
  const duration = hook?.duration ?? 0;
  useClipTime((t) => {
    setState(cues && preset ? stateAt(cues, t) : "");
    setHookOn(t < duration);
  });

  const look = preset ? spec.presets.find((p) => p.name === preset) : undefined;
  const shown = parseState(state);
  const cue = shown && cues ? cues[shown.cue] : null;
  const place = spec.positions[position];
  const hookLook = hook ? spec.hook.styles.find((s) => s.name === hook.style) : undefined;
  const hookPlace = hook ? spec.hook.positions[hook.position] : undefined;
  const area = spec.safe_area;

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden font-sans">
      {showSafeArea ? (
        <div
          className="absolute rounded-[2px] border border-dashed border-white/55 bg-white/[0.03]"
          style={{
            top: `${area.top * 100}%`,
            bottom: `${area.bottom * 100}%`,
            left: `${area.left * 100}%`,
            right: `${area.right * 100}%`,
          }}
        >
          <span className="absolute -bottom-[1px] left-1/2 -translate-x-1/2 translate-y-full rounded-sm bg-black/70 px-1.5 py-px text-[9px] font-medium tracking-wide text-white uppercase">
            Safe area
          </span>
        </div>
      ) : null}

      {cue && look ? (
        // Outer box places (it may translate); the inner box animates (scale + fade).
        <div className="absolute text-center" style={placementCss(place.alignment, place.margin_v + boxInset(look, place.alignment), place.margin_h, spec)}>
          <div
            key={shown!.cue}
            className="caption-in"
            style={{
              ["--grow-from" as string]: look.grow_from / 100,
              animationDuration: `${Math.max(look.fade_ms, look.grow_ms)}ms`,
            }}
          >
            {cue.lines.map((line, l) => (
              <div key={l}>
                <span style={textCss(look, spec)}>
                  {line.map((word, w) => {
                    const text = look.uppercase ? word.text.toUpperCase() : word.text;
                    const active = shown!.active.has(`${l}:${w}`);
                    return (
                      <span key={w}>
                        {w > 0 && !word.attached ? " " : null}
                        <span style={active ? { color: look.active } : undefined}>{text}</span>
                      </span>
                    );
                  })}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {hook && hookOn && hookLook && hookPlace && hook.text ? (
        <div className="absolute flex justify-center text-center" style={placementCss(hookPlace.alignment, hookPlace.margin_v + boxInset(hookLook, hookPlace.alignment), hookPlace.margin_h, spec)}>
          <div
            className="caption-in text-balance"
            style={{ maxWidth: cw(Math.min(hookLook.max_line_width, spec.output_width - 2 * hookPlace.margin_h - 2 * hookLook.outline), spec.output_width) }}
          >
            <span style={{ ...textCss(hookLook, spec), whiteSpace: "normal" }}>{hook.text}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** A miniature, static sample of a preset for its card: one line, the middle word emphasised. */
export function PresetSample({ spec, preset }: { spec: CaptionStyles; preset: DynamicPreset }) {
  const look = spec.presets.find((p) => p.name === preset);
  if (!look) return null;
  const words = ["say", "every", "word"];
  const scale = 0.16; // of the 1920 canvas: readable inside a card
  const css = textCss(look, spec);
  return (
    <span
      className="text-center"
      style={{ ...css, fontSize: `${(look.size * spec.font.em_per_size * scale).toFixed(1)}px`, textShadow: look.box ? undefined : outline(`${Math.max(1, look.outline * scale).toFixed(1)}px`, look.outline_colour, null), padding: look.box ? `1px ${Math.max(2, look.outline * scale).toFixed(1)}px` : undefined }}
    >
      {words.map((w, i) => (
        <span key={w}>
          {i ? " " : null}
          <span style={i === 1 ? { color: look.active } : undefined}>{look.uppercase ? w.toUpperCase() : w}</span>
        </span>
      ))}
    </span>
  );
}
