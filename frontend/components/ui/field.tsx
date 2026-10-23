import type { ComponentProps } from "react";
import { inputBase } from "@/components/ui/input-styles";

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
        className={`${inputBase} h-11 px-3.5 text-lead ${className}`}
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
