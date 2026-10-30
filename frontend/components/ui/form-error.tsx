import type { ReactNode } from "react";

/** Form-level error announced to assistive technology. Renders nothing when empty. */
export function FormError({ children }: { children?: ReactNode }) {
  return (
    <div role="alert" aria-live="polite">
      {children ? (
        <p className="rounded-control border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-sm text-rose-200">
          {children}
        </p>
      ) : null}
    </div>
  );
}
