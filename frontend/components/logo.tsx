import Link from "next/link";
import { useId } from "react";

export function LogoMark({ className = "size-7" }: { className?: string }) {
  // Unique per instance: a gradient defined inside a hidden copy (e.g. the desktop sidebar on a
  // phone) would otherwise leave every other copy without its stroke.
  const gradient = `peaksift-logo-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
      <defs>
        <linearGradient
          id={gradient}
          x1="0"
          y1="32"
          x2="32"
          y2="0"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#f97316" />
          <stop offset="1" stopColor="#fdba74" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="#18181b" />
      <rect
        x="0.5"
        y="0.5"
        width="31"
        height="31"
        rx="7.5"
        stroke="white"
        strokeOpacity="0.1"
      />
      <path
        d="M6 23l6.5-9 4 5 3.5-6.5L26 23"
        stroke={`url(#${gradient})`}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="20" cy="9" r="2" fill="#fdba74" />
    </svg>
  );
}

export function Logo() {
  return (
    <Link
      href="/"
      className="flex items-center gap-2.5 rounded-md font-semibold tracking-tight text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
    >
      <LogoMark />
      <span>
        PeakSift <span className="text-muted">AI</span>
      </span>
    </Link>
  );
}
