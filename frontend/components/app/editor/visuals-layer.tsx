"use client";

import { useContext, useEffect, useRef, useState, type CSSProperties } from "react";
import { useClipTime, VideoClockContext } from "@/components/app/editor/caption-layer";
import { assetTimeAt, insetRect, opacityAt, type VisualElementDraft, type VisualLayout } from "@/lib/visual-elements";
import { visualContentUrl, type VisualAsset } from "@/lib/visuals";

// Output-frame pixels → container units of the 9:16 frame (which declares container-type: size).
const cw = (px: number, layout: VisualLayout) => `${((px / layout.output.width) * 100).toFixed(3)}cqw`;
const ch = (px: number, layout: VisualLayout) => `${((px / layout.output.height) * 100).toFixed(3)}cqh`;

/** Keep a B-roll video on the preview's clock: its own time is offset + elapsed (wrapping
 * when looping), it plays only while the main video plays and the element is on screen, and
 * it is re-seeked whenever it drifts — never an independent clock. */
function useSyncedVideo(
  ref: React.RefObject<HTMLVideoElement | null>,
  element: VisualElementDraft,
  duration: number,
  t: number,
  mainPlaying: boolean,
) {
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const position = assetTimeAt(element, t, duration);
    if (position == null) {
      if (!video.paused) video.pause();
      return;
    }
    if (Math.abs(video.currentTime - position) > (mainPlaying ? 0.25 : 0.04)) video.currentTime = position;
    if (mainPlaying && video.paused) void video.play().catch(() => {});
    if (!mainPlaying && !video.paused) video.pause();
  }, [ref, element, duration, t, mainPlaying]);
}

function Media({
  projectId,
  asset,
  element,
  t,
  mainPlaying,
  className,
  style,
}: {
  projectId: string;
  asset: VisualAsset;
  element: VisualElementDraft;
  t: number;
  mainPlaying: boolean;
  className: string;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  useSyncedVideo(ref, element, asset.duration_seconds ?? 0, t, mainPlaying);
  const src = visualContentUrl(projectId, asset.id);
  if (asset.kind === "video") {
    return <video ref={ref} src={src} muted playsInline preload="auto" aria-hidden="true" tabIndex={-1} className={className} style={style} />;
  }
  // eslint-disable-next-line @next/next/no-img-element -- private, authenticated API image
  return <img src={src} alt="" aria-hidden="true" className={className} style={style} />;
}

/**
 * The edit's visual elements in the live preview, drawn in output-frame coordinates *under*
 * the caption layer (captions stay readable, as in the render). Cutaways cover the frame
 * (fill, or fit over a blurred copy); picture-in-picture and overlays sit in the renderer's
 * boxes; fades follow the renderer's ramp. The rendered MP4 remains authoritative.
 */
export function VisualsLayer({
  projectId,
  elements,
  assets,
  layout,
}: {
  projectId: string;
  elements: VisualElementDraft[];
  assets: Map<string, VisualAsset>;
  layout: VisualLayout | null;
}) {
  const [t, setT] = useState(0);
  useClipTime(setT);
  const clock = useContext(VideoClockContext);
  const [mainPlaying, setMainPlaying] = useState(false);
  useEffect(() => {
    const video = clock?.current;
    if (!video) return;
    const update = () => setMainPlaying(!video.paused && !video.ended);
    update();
    video.addEventListener("play", update);
    video.addEventListener("pause", update);
    video.addEventListener("ended", update);
    return () => {
      video.removeEventListener("play", update);
      video.removeEventListener("pause", update);
      video.removeEventListener("ended", update);
    };
  }, [clock]);

  if (!layout || !elements.length) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      {[...elements].sort((a, b) => Number(a.mode !== "cutaway") - Number(b.mode !== "cutaway")).map((element) => {
        const asset = assets.get(element.asset_id);
        if (!asset) return null;
        const visible = opacityAt(element, t);
        const hidden = visible <= 0;
        // Video elements stay mounted (preloaded, paused) so they are ready when they start.
        if (hidden && asset.kind !== "video") return null;
        const opacity = element.mode === "overlay" ? visible * element.opacity : visible;
        const flatten = asset.has_alpha && element.mode !== "overlay";
        if (element.mode === "cutaway") {
          return (
            <div
              key={element.key}
              className="absolute inset-0 overflow-hidden"
              style={{ opacity, visibility: hidden ? "hidden" : "visible", background: flatten ? layout.background : "#000" }}
            >
              {element.fit === "fit" ? (
                <Media projectId={projectId} asset={asset} element={element} t={t} mainPlaying={mainPlaying} className="absolute inset-0 size-full scale-110 object-cover blur-xl" />
              ) : null}
              <Media
                projectId={projectId}
                asset={asset}
                element={element}
                t={t}
                mainPlaying={mainPlaying}
                className={`absolute inset-0 size-full ${element.fit === "fit" ? "object-contain" : "object-cover"}`}
              />
            </div>
          );
        }
        const rect = insetRect(element, asset, layout);
        return (
          <div
            key={element.key}
            className="absolute overflow-hidden"
            style={{
              left: cw(rect.x, layout),
              top: ch(rect.y, layout),
              width: cw(rect.width, layout),
              height: ch(rect.height, layout),
              padding: rect.border ? cw(rect.border, layout) : 0,
              background: rect.border ? "#fff" : "transparent",
              opacity,
              visibility: hidden ? "hidden" : "visible",
            }}
          >
            <div className="relative size-full" style={{ background: flatten ? layout.background : "transparent" }}>
              <Media projectId={projectId} asset={asset} element={element} t={t} mainPlaying={mainPlaying} className="absolute inset-0 size-full object-contain" />
            </div>
          </div>
        );
      })}
    </div>
  );
}
