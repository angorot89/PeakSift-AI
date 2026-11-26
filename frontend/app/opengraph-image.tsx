import { ImageResponse } from "next/og";

export const alt = "PeakSift — find the moments worth clipping";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The picture shown when a PeakSift link is shared: the headline on PeakSift blue, with a waveform. */
export default function OpengraphImage() {
  const bars = Array.from({ length: 48 }, (_, i) => {
    const peak = (i > 8 && i < 14) || (i > 22 && i < 28) || (i > 36 && i < 40);
    return { height: Math.round((peak ? 0.75 : 0.25 + 0.2 * Math.abs(Math.sin(i * 0.9))) * 140), peak };
  });
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          background: "linear-gradient(150deg, #3d5afe 0%, #5b3dfe 100%)",
          color: "white",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 40, fontWeight: 800 }}>
          <div style={{ width: 64, height: 64, borderRadius: 16, background: "white", display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
            {[18, 30, 12, 44, 24].map((h, i) => (
              <div key={i} style={{ width: 6, height: h, borderRadius: 3, background: i === 3 ? "#3d5afe" : "#9aabff" }} />
            ))}
          </div>
          PeakSift
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 76, fontWeight: 800, lineHeight: 1.05, letterSpacing: -2 }}>Find the moments worth clipping.</div>
          <div style={{ fontSize: 32, marginTop: 20, opacity: 0.9 }}>Long videos into Shorts for YouTube, TikTok and Instagram.</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, height: 150 }}>
          {bars.map((bar, i) => (
            <div key={i} style={{ flex: 1, height: bar.height, borderRadius: 6, background: bar.peak ? "#ffd84d" : "rgba(255,255,255,0.35)" }} />
          ))}
        </div>
      </div>
    ),
    size,
  );
}
