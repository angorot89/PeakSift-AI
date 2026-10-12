"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, errorMessage } from "@/lib/api";

type ApiState<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Load data from the API with loading/error state and a `reload()`.
 * `load` must be referentially stable (module-level function or useCallback).
 * A 401 means the session is gone: the auth state is cleared so route guards redirect.
 */
export function useApi<T>(load: () => Promise<T>) {
  const { setUser } = useAuth();
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: true });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    load()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) setUser(null);
        setState({ data: null, error: errorMessage(err), loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [load, version, setUser]);

  const reload = useCallback(() => {
    setState((previous) => ({ ...previous, loading: true, error: null }));
    setVersion((v) => v + 1);
  }, []);

  return { ...state, reload };
}
