"use client";

import { X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";
import { IconButton } from "@/components/ui/icon-button";

type Placement = "center" | "palette" | "left" | "bottom" | "full";

const PLACEMENT: Record<Placement, string> = {
  center:
    "m-auto max-h-[calc(100dvh-2rem)] w-[min(var(--dialog-width),calc(100vw-2rem))] rounded-2xl border data-[open=true]:animate-dialog-in",
  palette:
    "mx-auto mt-[10dvh] mb-auto max-h-[min(34rem,80dvh)] w-[min(var(--dialog-width),calc(100vw-2rem))] rounded-2xl border data-[open=true]:animate-dialog-in",
  left: "my-0 mr-auto ml-0 h-dvh max-h-dvh w-[min(20rem,calc(100vw-3rem))] rounded-r-2xl border-r data-[open=true]:animate-sheet-left",
  bottom:
    "mx-0 mt-auto mb-0 max-h-[85dvh] w-full max-w-none rounded-t-2xl border-t data-[open=true]:animate-sheet-up",
  full: "m-0 h-dvh max-h-dvh w-full max-w-none rounded-none border-0 data-[open=true]:animate-sheet-up",
};

/**
 * A modal dialog or sheet on the native <dialog>: the page behind is inert, Escape closes it,
 * and the browser returns focus to the control that opened it. Clicking the backdrop closes it.
 * Mark the control that should receive focus first with `data-autofocus`.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  placement = "center",
  width = "36rem",
  hideTitle = false,
  headerActions,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  placement?: Placement;
  /** Center and palette dialogs only. */
  width?: string;
  /** Keep the title for assistive technology only (e.g. a navigation sheet). */
  hideTitle?: boolean;
  /** Extra controls beside Close (e.g. "Clear conversation"). */
  headerActions?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      // The first control a dialog is for (e.g. a confirmation field), rather than Close.
      dialog.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      data-open={open}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose(); // the backdrop
      }}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      style={{ ["--dialog-width" as string]: width }}
      className={`overflow-hidden border-border bg-surface p-0 text-foreground shadow-2xl backdrop:bg-black/70 ${PLACEMENT[placement]}`}
    >
      {open ? (
        <div className={`flex max-h-[inherit] flex-col ${placement === "full" ? "h-full" : ""}`}>
          <div className={`flex items-start justify-between gap-3 px-4 pt-4 sm:px-6 ${hideTitle ? "pb-0" : "border-b border-border pb-4"}`}>
            <div className={`min-w-0 ${hideTitle ? "sr-only" : ""}`}>
              <h2 id={titleId} className="text-title text-foreground">
                {title}
              </h2>
              {description ? (
                <p id={descriptionId} className="mt-0.5 text-sm text-muted">
                  {description}
                </p>
              ) : null}
            </div>
            <div className={`flex shrink-0 items-center gap-1 ${hideTitle ? "ml-auto" : ""}`}>
              {headerActions}
              <IconButton aria-label="Close" onClick={onClose}>
                <X aria-hidden="true" />
              </IconButton>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">{children}</div>
          {footer ? (
            <div className="flex flex-col-reverse gap-2 border-t border-border px-4 py-4 sm:flex-row sm:justify-end sm:px-6">
              {footer}
            </div>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
