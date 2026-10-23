"use client";

import { CheckCircle2, Info, X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

type Toast = { id: number; message: string; tone: "success" | "info" };
type ToastApi = (message: string, tone?: Toast["tone"]) => void;

const ToastContext = createContext<ToastApi | null>(null);
const LIFETIME_MS = 4500;

/**
 * Brief confirmation of a small completed action ("Transcript copied", "Insight hidden"). Problems
 * that need the creator stay inline, next to what they concern — never only in a toast.
 */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? (() => {});
}

function ToastItem({ toast, onDone }: { toast: Toast; onDone: (id: number) => void }) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useCallback(() => {
    timer.current = setTimeout(() => onDone(toast.id), LIFETIME_MS);
  }, [onDone, toast.id]);
  const stop = () => timer.current && clearTimeout(timer.current);
  useEffect(() => {
    start();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [start]);
  const Icon = toast.tone === "success" ? CheckCircle2 : Info;
  return (
    <li
      onMouseEnter={stop}
      onMouseLeave={start}
      className="pointer-events-auto flex animate-dialog-in items-center gap-3 rounded-xl border border-border-strong bg-surface-2 py-2.5 pr-2 pl-3.5 text-sm text-foreground shadow-2xl"
    >
      <Icon aria-hidden="true" className={`size-4 shrink-0 ${toast.tone === "success" ? "text-emerald-300" : "text-muted"}`} />
      <span className="min-w-0 flex-1">{toast.message}</span>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onDone(toast.id)}
        className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-white/[0.06] hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
      >
        <X aria-hidden="true" className="size-4" />
      </button>
    </li>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const show = useCallback<ToastApi>((message, tone = "success") => {
    const id = next.current++;
    setToasts((current) => [...current.slice(-2), { id, message, tone }]);
  }, []);
  const done = useCallback((id: number) => setToasts((current) => current.filter((t) => t.id !== id)), []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <ol
        aria-live="polite"
        aria-label="Notifications"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex flex-col items-center gap-2 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:items-end"
      >
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDone={done} />
        ))}
      </ol>
    </ToastContext.Provider>
  );
}
