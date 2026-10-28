// Brand Studio rules shared by the previews (pure, unit-tested). The server decides; these
// mirror app/services/branding/colors.py and clip_edit/brand.py so the preview shows what the
// render will do: hex-only colours, WCAG readability, and where the corner logo goes.

export type LogoCorner = "top_left" | "top_right" | "bottom_left" | "bottom_right";
export type LogoSize = "small" | "medium" | "large";
export type CaptionPlace = "top" | "center" | "bottom";

const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** `#RRGGBB` uppercase, or null when the text is not a hex colour. */
export function normalizeHex(value: string): string | null {
  const text = value.trim();
  if (!HEX.test(text)) return null;
  const digits = text.slice(1);
  const full = digits.length === 3 ? [...digits].map((d) => d + d).join("") : digits;
  return `#${full.toUpperCase()}`;
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

/** WCAG contrast ratio (1–21). */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export const TEXT_CONTRAST = 4.5;
export const CAPTION_SURROUND = "#101014";

/** Whether a colour may be the spoken word in captions (else captions keep their own colour). */
export function emphasisReadable(hex: string): boolean {
  return contrast(hex, CAPTION_SURROUND) >= TEXT_CONTRAST;
}

/** The more readable of near-black and white text on `background`. */
export function textOn(background: string): string {
  const dark = "#111114";
  const light = "#FFFFFF";
  return contrast(dark, background) >= contrast(light, background) ? dark : light;
}

/** Whether the Boxed hook can wear this accent (its text colour reads on it). */
export function accentUsable(hex: string): boolean {
  return contrast(textOn(hex), hex) >= TEXT_CONTRAST;
}

const isTop = (corner: LogoCorner) => corner.startsWith("top");
const flip = (corner: LogoCorner): LogoCorner => {
  const [vertical, side] = corner.split("_");
  return `${vertical === "top" ? "bottom" : "top"}_${side}` as LogoCorner;
};

export type LogoPlan = { corner: LogoCorner; moved: boolean; visibleFrom: number };

/** The renderer's placement policy: away from same-side captions; after a top hook. */
export function logoPlan(
  corner: LogoCorner,
  captions: CaptionPlace | null,
  hook: { position: "top" | "center"; seconds: number } | null,
): LogoPlan {
  let placed = corner;
  let moved = false;
  if ((captions === "bottom" && !isTop(corner)) || (captions === "top" && isTop(corner))) {
    placed = flip(corner);
    moved = true;
  }
  const visibleFrom = hook && hook.position === "top" && isTop(placed) ? hook.seconds : 0;
  return { corner: placed, moved, visibleFrom };
}

export const CORNER_LABELS: Record<LogoCorner, string> = {
  top_left: "Top left",
  top_right: "Top right",
  bottom_left: "Bottom left",
  bottom_right: "Bottom right",
};

export const SIZE_LABELS: Record<LogoSize, string> = { small: "Small", medium: "Medium", large: "Large" };

/** A creator-facing line explaining a move, or null. */
export function placementNote(plan: LogoPlan, wanted: LogoCorner): string | null {
  if (!plan.moved) return null;
  return `Shown ${CORNER_LABELS[plan.corner].toLowerCase()} so it stays clear of the captions (you chose ${CORNER_LABELS[wanted].toLowerCase()}).`;
}
