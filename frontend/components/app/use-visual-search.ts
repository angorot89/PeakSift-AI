"use client";

import { useEffect, useState } from "react";
import { errorMessage } from "@/lib/api";
import { SEARCH_DEBOUNCE_MS, searchVisuals, type VisualAsset, type VisualKind, type VisualSearchResults } from "@/lib/visuals";

/** Debounced server search; answers to an older query never replace a newer one's. */
export function useVisualSearch(projectId: string, text: string, kind: VisualKind | null, version: number) {
  const key = text ? `${kind ?? "all"}|${version}|${text}` : "";
  const [state, setState] = useState<{
    key: string;
    results: VisualSearchResults<VisualAsset> | null;
    error: string | null;
  }>({ key: "", results: null, error: null });
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const results = await searchVisuals(projectId, text, { kind });
        if (!cancelled) setState({ key, results, error: null });
      } catch (failure) {
        if (!cancelled) setState({ key, results: null, error: errorMessage(failure) });
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [projectId, key, text, kind]);
  const current = state.key === key;
  return {
    searching: Boolean(key) && !current,
    // The last answer stays on screen while a newer query is on its way (no flicker).
    results: key ? state.results : null,
    error: current ? state.error : null,
  };
}
