"use client";

import { Search } from "lucide-react";
import { createContext, useContext, useSyncExternalStore } from "react";
import { shortcutLabel } from "@/lib/command-menu";

/** The shell's command menu, opened from the page header's search field. */
export const ShellSearchContext = createContext<(() => void) | null>(null);

/** Whether this is a Mac (⌘K rather than Ctrl K); null while rendering on the server. */
export function useIsMac(): boolean | null {
  return useSyncExternalStore(
    () => () => undefined,
    () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent),
    () => null,
  );
}

/** A search field look that opens the command menu (projects, pages, or a question for Ask
 * PeakSift). Large screens only — phones have the search button in the top bar. */
export function ShellSearch() {
  const open = useContext(ShellSearchContext);
  const mac = useIsMac();
  if (!open) return null;
  return (
    <button
      type="button"
      onClick={open}
      aria-haspopup="dialog"
      aria-keyshortcuts={mac === null ? undefined : mac ? "Meta+K" : "Control+K"}
      className="hidden h-10 items-center gap-2.5 rounded-control border border-border bg-surface/80 px-3 text-sm text-subtle transition-colors hover:border-border-strong hover:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent lg:inline-flex lg:w-52 xl:w-72"
    >
      <Search aria-hidden="true" className="size-4 shrink-0" />
      <span className="flex-1 truncate text-left">Search or ask PeakSift…</span>
      {mac !== null ? (
        <kbd aria-hidden="true" className="rounded border border-border px-1.5 font-sans text-xs text-subtle">
          {shortcutLabel(mac)}
        </kbd>
      ) : null}
    </button>
  );
}
