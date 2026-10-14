"use client";

import { useEffect, useRef } from "react";
import { startPolling } from "@/lib/status-sync";

/** First status check shortly after a job becomes active (fast jobs finish in about a second). */
export const FIRST_POLL_MS = 1000;
export const POLL_INTERVAL_MS = 4000;

/**
 * Poll while `active`. The latest `tick` is read through a ref, so re-renders (and new
 * callback identities) never reset the timer; polling restarts only when `active` or `key`
 * changes. Polling stops when `active` turns false (the tick's state update ends it).
 */
export function usePolling(active: boolean, tick: () => Promise<unknown>, key: string | null = null) {
  const tickRef = useRef(tick);
  useEffect(() => {
    tickRef.current = tick;
  }, [tick]);
  useEffect(() => {
    if (!active) return;
    return startPolling(
      async () => {
        await tickRef.current();
        return true; // stopping is driven by `active` turning false
      },
      { firstDelayMs: FIRST_POLL_MS, intervalMs: POLL_INTERVAL_MS },
    );
  }, [active, key]);
}
