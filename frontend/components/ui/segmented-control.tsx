"use client";

/** A small set of mutually exclusive views or filters (pressed buttons, not tabs). */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  size = "md",
}: {
  label: string;
  options: readonly { value: T; label: string; count?: number; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-control border border-border bg-surface-2 p-0.5 [scrollbar-width:none]">
      {options.map((option) => {
        const pressed = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={pressed}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-[0.5rem] font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:text-subtle ${
              size === "sm" ? "h-7 px-2.5 text-caption pointer-coarse:h-11 pointer-coarse:min-w-11 justify-center" : "h-8 px-3 text-small pointer-coarse:h-11 pointer-coarse:min-w-11 justify-center"
            } ${pressed ? "bg-accent/[0.14] text-foreground shadow-[inset_0_0_0_1px_rgb(249_115_22/0.45)]" : "text-muted hover:text-foreground"}`}
          >
            {option.label}
            {option.count !== undefined ? <span className="tabular text-subtle">{option.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
