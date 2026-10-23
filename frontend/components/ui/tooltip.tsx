"use client";

import { cloneElement, type ReactElement, useId, useState } from "react";

/**
 * A short description shown on hover and keyboard focus, linked with aria-describedby. Never the
 * only way to reach information that matters: use it for icon-only controls and abbreviations.
 */
export function Tooltip({ text, children }: { text: string; children: ReactElement<Record<string, unknown>> }) {
  const id = useId();
  const [shown, setShown] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShown(true)}
      onMouseLeave={() => setShown(false)}
      onFocus={() => setShown(true)}
      onBlur={() => setShown(false)}
      onKeyDown={(event) => event.key === "Escape" && setShown(false)}
    >
      {cloneElement(children, { "aria-describedby": id })}
      <span
        id={id}
        role="tooltip"
        className={`pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 rounded-md bg-foreground px-2 py-1 text-caption font-medium whitespace-nowrap text-background shadow-lg transition-opacity ${
          shown ? "opacity-100" : "opacity-0"
        }`}
      >
        {text}
      </span>
    </span>
  );
}
