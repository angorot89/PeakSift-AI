import { useId } from "react";

/**
 * Decorative header art: layered ridges catching a warm dawn light — PeakSift's "peak". Drawn as
 * a small SVG (no photographs), faded into the page on the left, hidden from assistive technology
 * and on small screens.
 */
export function PeakArt() {
  const id = useId().replace(/:/g, "");
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 640 220"
      preserveAspectRatio="xMaxYMin slice"
      className="pointer-events-none absolute -top-8 right-0 bottom-0 hidden h-[calc(100%+2rem)] w-[42rem] max-w-[70%] [mask-image:linear-gradient(to_right,transparent,black_40%)] md:block"
    >
      <defs>
        <radialGradient id={`${id}-sun`} cx="0.62" cy="0.62" r="0.5">
          <stop offset="0" stopColor="#fdba74" stopOpacity="0.55" />
          <stop offset="0.35" stopColor="#f97316" stopOpacity="0.22" />
          <stop offset="1" stopColor="#f97316" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-rim`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#f97316" stopOpacity="0" />
          <stop offset="0.6" stopColor="#fdba74" stopOpacity="0.9" />
          <stop offset="1" stopColor="#f97316" stopOpacity="0.2" />
        </linearGradient>
        <linearGradient id={`${id}-fade`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.55" stopColor="#0a0a0c" stopOpacity="0" />
          <stop offset="1" stopColor="#0a0a0c" stopOpacity="1" />
        </linearGradient>
      </defs>
      <rect width="640" height="220" fill={`url(#${id}-sun)`} />
      <path d="M0 200 L90 150 L150 172 L250 104 L320 140 L390 82 L470 132 L560 96 L640 128 V220 H0 Z" fill="#17130f" />
      <path
        d="M120 220 L230 132 L290 158 L380 70 L430 104 L470 86 L560 150 L640 138 V220 Z"
        fill="#100d0b"
      />
      <path
        d="M230 132 L290 158 L380 70 L430 104 L470 86 L560 150"
        fill="none"
        stroke={`url(#${id}-rim)`}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <rect width="640" height="220" fill={`url(#${id}-fade)`} />
    </svg>
  );
}
