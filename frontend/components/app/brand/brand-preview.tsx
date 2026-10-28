"use client";

import { useState } from "react";
import { CaptionSampleLayer } from "@/components/app/editor/caption-layer";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { BrandLayout } from "@/lib/brand";
import {
  accentUsable,
  CORNER_LABELS,
  emphasisReadable,
  logoPlan,
  placementNote,
  textOn,
  type LogoCorner,
  type LogoSize,
} from "@/lib/brand-rules";
import type { CaptionStyles, DynamicPreset, HookPosition, HookStyle } from "@/lib/captions";

export type PreviewBrand = {
  name: string;
  primary: string;
  accent: string | null;
  emphasis: string | null;
  logoUrl: string | null;
  corner: LogoCorner;
  size: LogoSize;
  endText: string | null;
};

export type PreviewEdit = {
  captions: boolean;
  preset: DynamicPreset;
  captionPosition: "top" | "center" | "bottom";
  hook: boolean;
  hookStyle: HookStyle;
  hookPosition: HookPosition;
  hookSeconds: number;
  logo: boolean;
  endCard: boolean;
  endCardSeconds: number;
};

type Moment = "opening" | "during" | "end";

const SAMPLE_LINES = [["this", "changes"], ["everything"]];
const SAMPLE_HOOK = "Watch this before you build";

/**
 * A still preview of a branded Short on a sample background — no project needed. It uses the
 * renderer's own numbers (caption styles, logo boxes, safe-area margins, end-card geometry)
 * and its rules (readable colours only, the logo moving clear of captions and waiting for a
 * top hook). The final render remains authoritative. Decorative: its words are summarised for
 * assistive technology below it.
 */
export function BrandPreview({
  spec,
  layout,
  brand,
  edit,
}: {
  spec: CaptionStyles;
  layout: BrandLayout;
  brand: PreviewBrand;
  edit: PreviewEdit;
}) {
  const [moment, setMoment] = useState<Moment>("during");
  const W = layout.frame.width;
  const H = layout.frame.height;
  const cw = (px: number) => `${((px / W) * 100).toFixed(3)}cqw`;
  const ch = (px: number) => `${((px / H) * 100).toFixed(3)}cqh`;
  const hook = edit.hook ? { position: edit.hookPosition, seconds: edit.hookSeconds } : null;
  const plan = logoPlan(brand.corner, edit.captions ? edit.captionPosition : null, hook);
  const showHook = edit.hook && moment === "opening";
  const logoShown = edit.logo && brand.logoUrl && moment !== "end" && !(moment === "opening" && plan.visibleFrom > 0);
  const emphasis = brand.emphasis && emphasisReadable(brand.emphasis) ? brand.emphasis : null;
  const accent = brand.accent ?? brand.primary;
  const hookAccent = edit.hookStyle === "boxed" && accentUsable(accent) ? { box: accent, text: textOn(accent) } : null;
  const box = W * layout.logo_width_fraction[brand.size];
  const top = plan.corner.startsWith("top");
  const left = plan.corner.endsWith("left");
  const card = layout.card;
  const note = edit.logo && brand.logoUrl ? placementNote(plan, brand.corner) : null;

  const moments = [
    { value: "opening" as const, label: "Opening" },
    { value: "during" as const, label: "During" },
    ...(edit.endCard ? [{ value: "end" as const, label: "End card" }] : []),
  ];
  const current = moment === "end" && !edit.endCard ? "during" : moment;

  return (
    <figure className="flex flex-col items-center gap-3">
      <div
        className="relative aspect-[9/16] w-full max-w-[19rem] overflow-hidden rounded-2xl border border-border shadow-lg"
        style={{ containerType: "size" }}
      >
        {current === "end" ? (
          <div aria-hidden="true" className="absolute inset-0" style={{ backgroundColor: brand.primary }}>
            {brand.logoUrl && edit.logo ? (
              // eslint-disable-next-line @next/next/no-img-element -- a private, session-served image
              <img
                src={brand.logoUrl}
                alt=""
                className="absolute left-1/2 -translate-x-1/2 -translate-y-1/2 object-contain"
                style={{ top: `${card.logo_center_y * 100}%`, width: cw(W * card.logo_fraction), height: cw(W * card.logo_fraction) }}
              />
            ) : null}
            <p className="absolute inset-x-[6%] -translate-y-1/2 truncate text-center font-bold" style={{ top: `${card.name_y * 100}%`, color: textOn(brand.primary), fontSize: ch(84 * spec.font.em_per_size) }}>
              {brand.name || "Your brand"}
            </p>
            {brand.endText ? (
              <p className="absolute inset-x-[6%] -translate-y-1/2 truncate text-center" style={{ top: `${card.text_y * 100}%`, color: textOn(brand.primary), fontSize: ch(58 * spec.font.em_per_size) }}>
                {brand.endText}
              </p>
            ) : null}
          </div>
        ) : (
          <>
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{ background: "radial-gradient(circle at 50% 38%, #3a3f4b 0 18%, transparent 19%), radial-gradient(ellipse at 50% 78%, #2b2f38 0 32%, transparent 33%), linear-gradient(160deg, #1d2129, #121419 60%, #0d0f12)" }}
            />
            {edit.captions || showHook ? (
              <CaptionSampleLayer
                spec={spec}
                preset={edit.captions ? edit.preset : null}
                position={edit.captionPosition}
                lines={edit.captions ? SAMPLE_LINES : []}
                active={[0, 1]}
                activeColour={emphasis}
                hook={showHook ? { text: SAMPLE_HOOK, style: edit.hookStyle, position: edit.hookPosition } : null}
                hookAccent={hookAccent}
              />
            ) : null}
            {logoShown ? (
              // eslint-disable-next-line @next/next/no-img-element -- a private, session-served image
              <img
                src={brand.logoUrl!}
                alt=""
                aria-hidden="true"
                className="absolute object-contain"
                style={{
                  width: cw(box),
                  height: cw(box),
                  objectPosition: `${left ? "left" : "right"} ${top ? "top" : "bottom"}`,
                  ...(left ? { left: cw(layout.margins.left) } : { right: cw(layout.margins.right) }),
                  ...(top ? { top: ch(layout.margins.top) } : { bottom: ch(layout.margins.bottom) }),
                }}
              />
            ) : null}
          </>
        )}
      </div>
      <SegmentedControl label="Preview moment" options={moments} value={current} onChange={setMoment} size="sm" />
      <figcaption className="max-w-[19rem] text-center text-caption text-subtle">
        {current === "end"
          ? `Added after the clip: the Short gets ${edit.endCardSeconds}s longer.`
          : current === "opening" && plan.visibleFrom > 0 && edit.logo && brand.logoUrl
            ? "Your logo appears once the opening hook has ended."
            : (note ?? "A preview on a sample background. The final render is authoritative.")}
        <span className="sr-only">
          {` Preview: ${edit.captions ? `${edit.preset} captions at the ${edit.captionPosition}` : "no captions"}${
            edit.logo && brand.logoUrl ? `, logo ${CORNER_LABELS[plan.corner].toLowerCase()}` : ""
          }${emphasis ? ", spoken word in your emphasis colour" : ""}.`}
        </span>
      </figcaption>
    </figure>
  );
}
