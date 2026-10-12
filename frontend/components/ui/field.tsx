import type { ComponentProps } from "react";

type FieldProps = ComponentProps<"input"> & {
  id: string;
  label: string;
  error?: string | null;
};

/** Labelled text input with an accessible inline error. */
export function Field({ id, label, error, className = "", ...inputProps }: FieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-foreground">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={`h-11 w-full rounded-lg border border-border bg-white/[0.03] px-3.5 text-[15px] text-foreground outline-none transition-colors placeholder:text-subtle focus:border-accent/60 focus-visible:ring-2 focus-visible:ring-accent/40 aria-[invalid=true]:border-rose-500/60 ${className}`}
        {...inputProps}
      />
      {error ? (
        <p id={errorId} className="text-sm text-rose-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
