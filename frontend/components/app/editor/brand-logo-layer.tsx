"use client";

import { useEffect, useState } from "react";
import { useClipTime, useShortTime } from "@/components/app/editor/caption-layer";
import { getBrandLayout, listLogoCandidates, logoUrl, type BrandLayout } from "@/lib/brand";
import { logoPlan, type CaptionPlace, type LogoCorner, type LogoSize } from "@/lib/brand-rules";

/**
 * The brand's corner logo over the editor's live preview, placed by the renderer's numbers and
 * rules (clear of same-side captions, after a top hook). Decorative; the render is authoritative.
 */
export function BrandLogoLayer({
  logo,
  captions,
  hook,
}: {
  logo: { asset_id: string; corner: LogoCorner; size: LogoSize };
  captions: CaptionPlace | null;
  hook: { position: "top" | "center"; seconds: number } | null;
}) {
  const [layout, setLayout] = useState<BrandLayout | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const toShort = useShortTime();
  useClipTime((clipTime) => {
    const t = toShort(clipTime);
    setTime((previous) => (Math.abs(previous - t) > 0.05 ? t : previous));
  });
  useEffect(() => {
    let cancelled = false;
    Promise.all([getBrandLayout(), listLogoCandidates()])
      .then(([numbers, candidates]) => {
        if (cancelled) return;
        setLayout(numbers);
        const found = candidates.find((c) => c.id === logo.asset_id);
        setSrc(found ? logoUrl(found) : null);
      })
      .catch(() => undefined); // the preview simply shows no logo
    return () => {
      cancelled = true;
    };
  }, [logo.asset_id]);
  if (!layout || !src) return null;
  const plan = logoPlan(logo.corner, captions, hook);
  if (time < plan.visibleFrom) return null;
  const W = layout.frame.width;
  const H = layout.frame.height;
  const box = `${((W * layout.logo_width_fraction[logo.size]) / W) * 100}cqw`;
  const top = plan.corner.startsWith("top");
  const left = plan.corner.endsWith("left");
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a private, session-served image
    <img
      src={src}
      alt=""
      aria-hidden="true"
      className="pointer-events-none absolute object-contain"
      style={{
        width: box,
        height: box,
        objectPosition: `${left ? "left" : "right"} ${top ? "top" : "bottom"}`,
        ...(left ? { left: `${(layout.margins.left / W) * 100}cqw` } : { right: `${(layout.margins.right / W) * 100}cqw` }),
        ...(top ? { top: `${(layout.margins.top / H) * 100}cqh` } : { bottom: `${(layout.margins.bottom / H) * 100}cqh` }),
      }}
    />
  );
}
