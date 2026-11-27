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
import { captionFontFamily } from "@/components/app/editor/caption-fonts";
import { cueAt, parseState, spokenCount, stateAt, type PreviewCue } from "@/lib/caption-timing";
import type { CaptionStyles, DynamicPreset, HookPosition, HookStyle, PresetSpec } from "@/lib/captions";

/** The preview's playing video, provided by the stage so overlays follow its clock. */
export const VideoClockContext = createContext<RefObject<HTMLVideoElement | null> | null>(null);

/** With Tighten: how the clip's time maps onto the Short's (shorter) timeline. The hook,
 * visuals, logo, sounds and the timeline are on the Short's timeline; captions come from the
 * clip's own words, in the clip's time. Absent when nothing is cut. */
export type ShortTimeMap = { toShort: (t: number) => number; toClip: (t: number) => number; seconds: number };
export const ShortTimeContext = createContext<ShortTimeMap | null>(null);

/** The Short's time of a clip time (the same time when nothing is cut). */
export function useShortTime(): (t: number) => number {
  return useContext(ShortTimeContext)?.toShort ?? identity;
}
const identity = (t: number) => t;

type VideoWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

/** Call `onTime` with the clip time of every presented frame (rVFC, rAF fallback) and on seeks. */
export function useClipTime(onTime: (t: number) => void) {
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
  // Creator styles (V2.0): a display font with its own em ratio, and a soft glow.
  font?: string | null;
  em_per_size?: number;
  glow?: number;
};

// Noto Sans' CSS content area (hhea ascent + descent): what an inline background covers.
const CONTENT_EM = 1.362;

/** CSS for libass-styled text: same size (em = size × em_per_size), weight, outline or box. */
function textCss(look: TextLook, spec: CaptionStyles): CSSProperties {
  const h = spec.output_height;
  const em = look.em_per_size ?? spec.font.em_per_size;
  const css: CSSProperties = {
    fontSize: ch(look.size * em, h),
    lineHeight: 1 / em, // libass line height is the font size
    fontWeight: look.bold ? 700 : 400,
    color: look.text,
    fontFamily: captionFontFamily(look.font),
    whiteSpace: "nowrap", // the renderer already chose the lines
  };
  if (look.box) {
    css.backgroundColor = rgba(look.outline_colour, (255 - look.box_alpha) / 255);
    // libass boxes the whole line (the font size) plus the outline on every side.
    const vertical = (look.size * (1 - spec.font.em_per_size * CONTENT_EM)) / 2 + look.outline;
    css.padding = `${ch(vertical, h)} ${ch(look.outline, h)}`;
    css.boxDecorationBreak = "clone";
    css.WebkitBoxDecorationBreak = "clone";
  } else if (look.glow) {
    // libass blurs the outline (\\blur): a soft halo of the outline colour around the letters.
    const ring = outline(ch(look.outline * 0.6, h), look.outline_colour, null);
    css.textShadow = `${ring}, 0 0 ${ch(look.glow * 2, h)} ${look.outline_colour}, 0 0 ${ch(look.glow * 4, h)} ${look.outline_colour}`;
  } else {
    css.textShadow = outline(ch(look.outline, h), look.outline_colour, look.shadow ? ch(look.shadow, h) : null);
  }
  return css;
}

/** How the spoken word stands out, as the renderer draws it: its colour, a marker outline or an
 * underline, and a pop (a few percent larger). Every word is inline-block when a style pops, so
 * the growing word animates like the render. */
function wordCss(look: PresetSpec, spec: CaptionStyles, active: boolean, colour?: string | null): CSSProperties | undefined {
  const h = spec.output_height;
  const css: CSSProperties = {};
  if (look.pop > 100) {
    css.display = "inline-block";
    css.transition = "transform 90ms ease-out";
    css.transform = active ? `scale(${look.pop / 100})` : "scale(1)";
  }
  if (!active) return look.pop > 100 ? css : undefined;
  css.color = colour ?? look.active;
  if (look.highlight === "marker" && look.marker) {
    css.textShadow = outline(ch(look.marker_outline, h), look.marker, null);
  } else if (look.highlight === "underline") {
    css.textDecorationLine = "underline";
    css.textDecorationThickness = ch(look.size * 0.06, h);
    css.textUnderlineOffset = ch(look.size * 0.08, h);
  }
  return css;
}

// libass pads a box by the outline; box styles sit that much further in so the box stays inside.
// A marker style's spoken word has a wider outline than its text: it sits that much further in.
const boxInset = (look: TextLook & { highlight?: string; marker_outline?: number }, alignment: number) => {
  if (alignment === 5) return 0;
  const box = look.box ? Math.round(look.outline) : 0;
  const marker = look.highlight === "marker" ? Math.round(Math.max(0, (look.marker_outline ?? 0) - look.outline)) : 0;
  return box + marker;
};

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
  const [spoken, setSpoken] = useState(Number.POSITIVE_INFINITY);
  const [hookOn, setHookOn] = useState(false);
  const duration = hook?.duration ?? 0;
  const toShort = useShortTime();
  const look = preset ? spec.presets.find((p) => p.name === preset) : undefined;
  const reveal = !!look?.reveal;
  useClipTime((t) => {
    setState(cues && preset ? stateAt(cues, t) : "");
    if (reveal && cues) {
      const index = cueAt(cues, t);
      setSpoken(index < 0 ? Number.POSITIVE_INFINITY : spokenCount(cues[index], t));
    }
    setHookOn(toShort(t) < duration);
  });

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
            {cue.lines.map((line, l) => {
              const before = cue.lines.slice(0, l).reduce((n, words) => n + words.length, 0);
              return (
                <div key={l} dir="auto">
                  <span style={textCss(look, spec)}>
                    {line.map((word, w) => {
                      const text = look.uppercase ? word.text.toUpperCase() : word.text;
                      const active = shown!.active.has(`${l}:${w}`);
                      // Reveal: words not yet spoken keep their place but are not drawn.
                      const hidden = reveal && before + w >= spoken;
                      return (
                        <span key={w} style={hidden ? { opacity: 0 } : undefined}>
                          {w > 0 && !word.attached ? " " : null}
                          <span style={wordCss(look, spec, active)}>{text}</span>
                        </span>
                      );
                    })}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {hook && hookOn && hookLook && hookPlace && hook.text ? (
        <div className="absolute flex justify-center text-center" style={placementCss(hookPlace.alignment, hookPlace.margin_v + boxInset(hookLook, hookPlace.alignment), hookPlace.margin_h, spec)}>
          <div
            className="caption-in text-balance"
            style={{ maxWidth: cw(Math.min(hookLook.max_line_width, spec.output_width - 2 * hookPlace.margin_h - 2 * hookLook.outline), spec.output_width) }}
          >
            <span dir="auto" style={{ ...textCss(hookLook, spec), whiteSpace: "normal" }}>{hook.text}</span>
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
  const arabic = look.scripts[0] === "arabic";
  const words = look.one_word ? ["every"] : arabic ? ["قل", "كل", "كلمة"] : ["say", "every", "word"];
  const scale = look.one_word ? 0.11 : 0.16; // of the 1920 canvas: readable inside a card
  const css = textCss(look, spec);
  const px = (value: number) => `${Math.max(1, value * scale).toFixed(1)}px`;
  const ring = look.box ? undefined : outline(px(look.glow ? look.outline * 0.6 : look.outline), look.outline_colour, null);
  return (
    <span
      className="text-center"
      dir={arabic ? "rtl" : undefined}
      style={{
        ...css,
        fontSize: `${(look.size * look.em_per_size * scale).toFixed(1)}px`,
        textShadow: look.glow && ring ? `${ring}, 0 0 ${px(look.glow * 3)} ${look.outline_colour}` : ring,
        padding: look.box ? `1px ${px(look.outline)}` : undefined,
      }}
    >
      {words.map((w, i) => {
        const active = look.one_word || i === 1;
        const css = wordCss(look, spec, active);
        const shown = look.reveal && i === 2 ? { opacity: 0.18 } : undefined;
        return (
          <span key={w} style={shown}>
            {i ? " " : null}
            <span
              style={
                css && look.highlight === "marker" && active && look.marker
                  ? { ...css, textShadow: outline(px(look.marker_outline), look.marker, null) }
                  : css && look.highlight === "underline" && active
                    ? { ...css, textDecorationThickness: "2px", textUnderlineOffset: "3px" }
                    : css
              }
            >
              {look.uppercase ? w.toUpperCase() : w}
            </span>
          </span>
        );
      })}
    </span>
  );
}

/**
 * A still frame of captions and the hook for previews without a video (Brand Studio, the
 * template builder): the same renderer numbers and CSS as the editor's live layer, with an
 * optional brand emphasis colour for the spoken word and a brand accent for the Boxed hook.
 */
export function CaptionSampleLayer({
  spec,
  preset,
  position,
  lines,
  active,
  activeColour,
  hook,
  hookAccent,
}: {
  spec: CaptionStyles;
  preset: DynamicPreset | null;
  position: "top" | "center" | "bottom";
  lines: string[][];
  /** [line, word] of the spoken word. */
  active: [number, number] | null;
  activeColour?: string | null;
  hook: { text: string; style: HookStyle; position: HookPosition } | null;
  hookAccent?: { box: string; text: string } | null;
}) {
  const look = preset ? spec.presets.find((p) => p.name === preset) : undefined;
  const place = spec.positions[position];
  const hookStyle = hook ? spec.hook.styles.find((s) => s.name === hook.style) : undefined;
  const hookLook = hookStyle && hookStyle.box && hookAccent ? { ...hookStyle, outline_colour: hookAccent.box, text: hookAccent.text } : hookStyle;
  const hookPlace = hook ? spec.hook.positions[hook.position] : undefined;
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden font-sans">
      {look && lines.length ? (
        <div className="absolute text-center" style={placementCss(place.alignment, place.margin_v + boxInset(look, place.alignment), place.margin_h, spec)}>
          {lines.map((line, l) => (
            <div key={l} dir="auto">
              <span style={textCss(look, spec)}>
                {line.map((word, w) => {
                  const text = look.uppercase ? word.toUpperCase() : word;
                  const on = active !== null && active[0] === l && active[1] === w;
                  return (
                    <span key={w}>
                      {w > 0 ? " " : null}
                      <span style={wordCss(look, spec, on, activeColour)}>{text}</span>
                    </span>
                  );
                })}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {hook && hookLook && hookPlace && hook.text ? (
        <div className="absolute flex justify-center text-center" style={placementCss(hookPlace.alignment, hookPlace.margin_v + boxInset(hookLook, hookPlace.alignment), hookPlace.margin_h, spec)}>
          <div className="text-balance" style={{ maxWidth: cw(Math.min(hookLook.max_line_width, spec.output_width - 2 * hookPlace.margin_h - 2 * hookLook.outline), spec.output_width) }}>
            <span dir="auto" style={{ ...textCss(hookLook, spec), whiteSpace: "normal" }}>{hook.text}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
