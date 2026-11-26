"use client";

/** A small set of mutually exclusive views or filters (pressed buttons, not tabs). */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  size = "md",
  wrap = false,
}: {
  label: string;
  options: readonly {
    value: T;
    label: string;
    count?: number;
    disabled?: boolean;
    /** A coloured dot before the label (a status colour class such as `bg-success`); the label
     * still says what it is. */
    dot?: string;
  }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
  /** Wrap onto a second line instead of scrolling sideways (when every option must stay visible). */
  wrap?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={`inline-flex max-w-full rounded-control border border-border bg-surface-2 p-0.5 ${wrap ? "flex-wrap" : "overflow-x-auto [scrollbar-width:none]"}`}
    >
      {options.map((option) => {
        const pressed = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={pressed}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-[0.375rem] font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:text-subtle ${
              size === "sm" ? "h-7 px-2.5 text-caption pointer-coarse:h-11 pointer-coarse:min-w-11 justify-center" : "h-8 px-3 text-small pointer-coarse:h-11 pointer-coarse:min-w-11 justify-center"
            } ${pressed ? "bg-background text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]" : "text-muted hover:text-foreground"}`}
          >
            {option.dot ? <span aria-hidden="true" className={`size-1.5 rounded-full ${option.dot}`} /> : null}
            {option.label}
            {option.count !== undefined ? (
              <span className="tabular rounded-full bg-surface-3 px-1.5 text-caption text-muted">{option.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
