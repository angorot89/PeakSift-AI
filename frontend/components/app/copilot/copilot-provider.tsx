"use client";

import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

type CopilotState = {
  open: boolean;
  /** Each call to openCopilot, counted: the panel takes a queued question even when already open. */
  request: number;
  /** Open the panel; an optional question is asked right away (e.g. from the command menu). Focus
   * returns to `returnTo` (default: what has focus now) when the panel closes. */
  openCopilot: (question?: string, returnTo?: HTMLElement | null) => void;
  closeCopilot: () => void;
  /** A question waiting to be asked once the panel is open (read once, then cleared). */
  takeQueued: () => string | null;
};

const CopilotContext = createContext<CopilotState | null>(null);

/** Whether Ask PeakSift is open, shared by its entry points and the panel. Focus goes back to
 * whatever opened it when it closes. */
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [request, setRequest] = useState(0);
  const opener = useRef<HTMLElement | null>(null);
  const queued = useRef<string | null>(null);
  const openCopilot = useCallback((question?: string, returnTo?: HTMLElement | null) => {
    const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // Opening again while open keeps the original opener.
    if (!opener.current) opener.current = returnTo ?? focused;
    queued.current = question?.trim() || null;
    setRequest((count) => count + 1);
    setOpen(true);
  }, []);
  const closeCopilot = useCallback(() => {
    setOpen(false);
    const target = opener.current;
    opener.current = null;
    if (target && document.contains(target)) window.setTimeout(() => target.focus(), 0);
  }, []);
  const takeQueued = useCallback(() => {
    const question = queued.current;
    queued.current = null;
    return question;
  }, []);
  const value = useMemo(
    () => ({ open, request, openCopilot, closeCopilot, takeQueued }),
    [open, request, openCopilot, closeCopilot, takeQueued],
  );
  return <CopilotContext.Provider value={value}>{children}</CopilotContext.Provider>;
}

export function useCopilot(): CopilotState {
  const value = useContext(CopilotContext);
  if (!value) throw new Error("useCopilot outside CopilotProvider");
  return value;
}
