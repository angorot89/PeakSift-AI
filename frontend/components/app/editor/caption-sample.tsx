import type { CSSProperties } from "react";
import type { CaptionPosition, CaptionStyle } from "@/lib/edits";

/**
 * Browser approximations of the server's caption presets (see caption_styles.py): same
 * size ratios on the 1080 × 1920 canvas, weight, colour, outline/box and margins. They
 * communicate the preset's intent; the FFmpeg/libass render is the authoritative output.
 */
const PRESET = {
  // size and outline in px on the 1920-high canvas
  clean: { size: 62, weight: 400, color: "#ffffff", outline: 3, box: false },
  bold: { size: 80, weight: 700, color: "#ffffff", outline: 6, box: false },
  creator: { size: 72, weight: 700, color: "#ffe14d", outline: 0, box: true },
} as const;

const CANVAS_HEIGHT = 1920;

function outline(px: string): string {
  const steps = [
    [1, 0], [-1, 0], [0, 1], [0, -1], [0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7],
  ];
  return steps.map(([x, y]) => `calc(${x} * ${px}) calc(${y} * ${px}) 0 #000`).join(", ");
}

/** Style for caption text sized relative to a container (`unit` = 1% of the frame height). */
export function captionTextStyle(style: CaptionStyle, unit: (fractionOfHeight: number) => string): CSSProperties {
  const p = PRESET[style];
  const css: CSSProperties = {
    fontSize: unit(p.size / CANVAS_HEIGHT),
    fontWeight: p.weight,
    color: p.color,
    lineHeight: 1.2,
    letterSpacing: "-0.005em",
  };
  if (p.box) {
    css.backgroundColor = "rgb(0 0 0 / 0.8)";
    css.padding = `${unit(10 / CANVAS_HEIGHT)} ${unit(18 / CANVAS_HEIGHT)}`;
    css.boxDecorationBreak = "clone";
    css.WebkitBoxDecorationBreak = "clone";
  } else {
    css.textShadow = outline(unit(p.outline / CANVAS_HEIGHT));
  }
  return css;
}

const POSITION_STYLE: Record<CaptionPosition, CSSProperties> = {
  top: { top: `${(260 / CANVAS_HEIGHT) * 100}%` },
  center: { top: "50%", transform: "translateY(-50%)" },
  bottom: { bottom: `${(320 / CANVAS_HEIGHT) * 100}%` },
};

/** A caption laid over a 9:16 frame that declares `container-type: size`. */
export function CaptionOverlay({
  text,
  style,
  position,
}: {
  text: string;
  style: CaptionStyle;
  position: CaptionPosition;
}) {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute right-[8.33%] left-[8.33%] text-center transition-[top,bottom,transform] duration-300"
      style={POSITION_STYLE[position]}
    >
      <span style={captionTextStyle(style, (f) => `${(f * 100).toFixed(3)}cqh`)}>{text}</span>
    </div>
  );
}
