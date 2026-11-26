import Link from "next/link";

/**
 * The mark: a short stretch of waveform on PeakSift blue in which one peak stands out — what
 * PeakSift does to a long recording.
 */
export function LogoMark({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="8" fill="#3d5afe" />
      <g strokeWidth="2.6" strokeLinecap="round" stroke="#ffffff">
        <path d="M7 14.5v3" strokeOpacity="0.6" />
        <path d="M11.5 12v8" strokeOpacity="0.75" />
        <path d="M16 15v2" strokeOpacity="0.6" />
        <path d="M20.5 7.5v17" />
        <path d="M25 13v6" strokeOpacity="0.75" />
      </g>
    </svg>
  );
}

export function Logo() {
  return (
    <Link
      href="/"
      className="flex min-h-11 items-center gap-2.5 rounded-md font-display text-lg font-extrabold tracking-tight text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
    >
      <LogoMark />
      <span className="whitespace-nowrap">
        PeakSift <span className="font-normal text-subtle">AI</span>
      </span>
    </Link>
  );
}
