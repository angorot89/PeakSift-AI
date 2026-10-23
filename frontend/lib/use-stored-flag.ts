"use client";

import { useCallback, useSyncExternalStore } from "react";

// Small per-browser preferences (a collapsed sidebar, a dismissed tip). A convenience only:
// storage can be unavailable (private mode), and then the choice lasts until the page reloads.
const listeners = new Set<() => void>();
const memory = new Map<string, boolean>();

function read(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return memory.get(key) ?? false;
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** A boolean remembered in this browser under `key` (false until set). */
export function useStoredFlag(key: string): [boolean, (value: boolean) => void] {
  const value = useSyncExternalStore(subscribe, () => read(key), () => false);
  const set = useCallback(
    (next: boolean) => {
      memory.set(key, next);
      try {
        window.localStorage.setItem(key, next ? "1" : "0");
      } catch {
        // kept in memory for this page instead
      }
      listeners.forEach((listener) => listener());
    },
    [key],
  );
  return [value, set];
}
