import Link from "next/link";

/**
 * The mark: a short stretch of waveform in which one peak is picked out in the signal colour —
 * what PeakSift does to a long recording.
 */
export function LogoMark({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="7" fill="#1d1e22" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="6.5" stroke="#3b3e46" />
      <g strokeWidth="2.6" strokeLinecap="round">
        <path d="M7 14.5v3" stroke="#8d919a" />
        <path d="M11.5 12v8" stroke="#a9acb4" />
        <path d="M16 15v2" stroke="#8d919a" />
        <path d="M20.5 7.5v17" stroke="#e3f25c" />
        <path d="M25 13v6" stroke="#a9acb4" />
      </g>
    </svg>
  );
}

export function Logo() {
  return (
    <Link
      href="/"
      className="flex min-h-11 items-center gap-2.5 rounded-md font-semibold tracking-tight text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
    >
      <LogoMark />
      <span className="whitespace-nowrap">
        PeakSift <span className="font-normal text-subtle">AI</span>
      </span>
    </Link>
  );
}
