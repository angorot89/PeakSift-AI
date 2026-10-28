"use client";

import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

type CopilotState = {
  open: boolean;
  /** Open the panel; an optional question is asked right away (e.g. from the command menu). */
  openCopilot: (question?: string) => void;
  closeCopilot: () => void;
  /** A question waiting to be asked once the panel is open (read once, then cleared). */
  takeQueued: () => string | null;
};

const CopilotContext = createContext<CopilotState | null>(null);

/** Whether Ask PeakSift is open, shared by its entry points and the panel. Focus goes back to
 * whatever opened it when it closes. */
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const queued = useRef<string | null>(null);
  const openCopilot = useCallback((question?: string) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    queued.current = question?.trim() || null;
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
    () => ({ open, openCopilot, closeCopilot, takeQueued }),
    [open, openCopilot, closeCopilot, takeQueued],
  );
  return <CopilotContext.Provider value={value}>{children}</CopilotContext.Provider>;
}

export function useCopilot(): CopilotState {
  const value = useContext(CopilotContext);
  if (!value) throw new Error("useCopilot outside CopilotProvider");
  return value;
}
