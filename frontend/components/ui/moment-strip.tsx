const BARS = 96;
/** Three stretches of the illustration marked as moments: [first bar, last bar, label]. */
const MOMENTS: [number, number, string][] = [
  [14, 21, "04:12"],
  [49, 57, "21:37"],
  [78, 83, "38:05"],
];

const inMoment = (index: number) => MOMENTS.some(([from, to]) => index >= from && index <= to);

/** A deterministic, speech-like envelope (no randomness: server and browser draw the same bars). */
function barHeight(index: number): number {
  const base = 0.28 + 0.16 * Math.sin(index * 0.9) * Math.sin(index * 0.23) + 0.1 * Math.sin(index * 2.7);
  const peak = inMoment(index) ? 0.42 + 0.12 * Math.sin(index * 1.7) : 0;
  return Math.min(1, Math.max(0.1, base + peak));
}

/**
 * PeakSift's picture of itself: a long recording as a waveform, with the moments it would mark
 * picked out in blue. Decorative (hidden from assistive technology); the page around it says the
 * same thing in words. Labelled as an illustration.
 */
export function MomentStrip({ className = "", compact = false }: { className?: string; compact?: boolean }) {
  return (
    <figure aria-hidden="true" className={className}>
      <div className={`relative ${compact ? "h-32" : "h-40 sm:h-52"}`}>
        <div className="absolute inset-0 flex items-center gap-px sm:gap-[3px]">
          {Array.from({ length: BARS }, (_, index) => (
            <span
              key={index}
              className={`hero-bar flex-1 rounded-full ${inMoment(index) ? "bg-accent" : "bg-surface-3"}`}
              style={{ height: `${(barHeight(index) * 100).toFixed(2)}%`, animationDelay: `${index * 6}ms` }}
            />
          ))}
        </div>
        {MOMENTS.map(([from, to, label]) => (
          <span
            key={label}
            className="hero-mark absolute -top-7 flex flex-col"
            style={{ left: `${(from / BARS) * 100}%`, width: `${((to - from + 1) / BARS) * 100}%` }}
          >
            <span className="tabular text-caption font-medium text-foreground">{label}</span>
            <span className="mt-1 h-1.5 border-x border-t border-accent" />
          </span>
        ))}
      </div>
      <div className="tabular mt-3 flex justify-between text-caption text-subtle">
        <span>00:00</span>
        <span>A 45-minute recording (illustration)</span>
        <span>45:00</span>
      </div>
    </figure>
  );
}
