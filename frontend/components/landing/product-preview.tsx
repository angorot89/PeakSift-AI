const BAR_COUNT = 72;
const highlights: Array<[number, number]> = [
  [12, 20],
  [34, 41],
  [55, 62],
];

const bars = Array.from({ length: BAR_COUNT }, (_, i) => {
  const height = 0.2 + 0.8 * Math.abs(Math.sin(i * 0.7) * Math.cos(i * 0.23));
  const highlighted = highlights.some(([start, end]) => i >= start && i <= end);
  return { height: Math.round(height * 100), highlighted };
});

const clips = ["YouTube Shorts", "TikTok", "Instagram Reels"];

export function ProductPreview() {
  return (
    <section aria-label="Product preview" className="mx-auto max-w-6xl px-6 pb-24">
      <div className="relative rounded-2xl border border-border bg-surface/80 p-2 shadow-2xl shadow-black/50">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -inset-px -z-10 rounded-2xl bg-gradient-to-b from-accent/20 to-transparent blur-2xl"
        />

        <div className="flex items-center justify-between px-3 py-2">
          <div className="flex gap-1.5" aria-hidden="true">
            <span className="size-2.5 rounded-full bg-white/10" />
            <span className="size-2.5 rounded-full bg-white/10" />
            <span className="size-2.5 rounded-full bg-white/10" />
          </div>
          <span className="text-xs text-subtle">Illustrative preview</span>
        </div>

        <div className="grid gap-2 lg:grid-cols-5">
          <div className="rounded-xl border border-border bg-background p-4 lg:col-span-3">
            <p className="text-xs font-medium tracking-wide text-subtle uppercase">
              Long-form source
            </p>
            <div className="relative mt-3 flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-gradient-to-br from-zinc-800 via-zinc-900 to-zinc-950">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_40%,rgb(249_115_22/0.12),transparent_60%)]" />
              <span className="relative flex size-12 items-center justify-center rounded-full border border-white/15 bg-white/10 backdrop-blur">
                <svg viewBox="0 0 24 24" className="ml-0.5 size-5 fill-white" aria-hidden="true">
                  <path d="M8 5.5v13l10-6.5-10-6.5z" />
                </svg>
              </span>
            </div>

            <div className="mt-4">
              <div className="flex items-center justify-between text-xs text-subtle">
                <span>Timeline</span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-sm bg-accent" />
                  Candidate moments
                </span>
              </div>
              <div className="mt-2 flex h-16 items-center gap-[2px]" aria-hidden="true">
                {bars.map((bar, i) => (
                  <span
                    key={i}
                    className={`flex-1 rounded-full ${bar.highlighted ? "bg-accent" : "bg-white/15"}`}
                    style={{ height: `${bar.height}%` }}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="flex flex-col rounded-xl border border-border bg-background p-4 lg:col-span-2">
            <p className="text-xs font-medium tracking-wide text-subtle uppercase">
              Short-form clips
            </p>
            <div className="mt-3 grid grid-cols-3 gap-2 lg:my-auto">
              {clips.map((platform) => (
                <div key={platform} className="flex flex-col gap-2">
                  <div className="relative flex aspect-[9/16] flex-col justify-end overflow-hidden rounded-lg bg-gradient-to-b from-zinc-800 to-zinc-950 p-2">
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgb(249_115_22/0.14),transparent_65%)]" />
                    <div className="relative space-y-1" aria-hidden="true">
                      <span className="block h-1.5 w-full rounded-full bg-white/70" />
                      <span className="mx-auto block h-1.5 w-2/3 rounded-full bg-accent-soft/80" />
                    </div>
                  </div>
                  <span className="text-center text-caption leading-tight text-subtle">
                    {platform}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
