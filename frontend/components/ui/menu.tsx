"use client";

import type { LucideIcon } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { menuIndex } from "@/lib/menu-keys";

export type MenuItem = { label: string; icon?: LucideIcon; onSelect: () => void; tone?: "danger"; disabled?: boolean };

/**
 * A menu button: arrow keys move between items, Enter/Space choose, Escape or Tab close it and
 * focus returns to the button; a click elsewhere closes it.
 */
export function Menu({
  label,
  trigger,
  items,
  align = "end",
  side = "below",
  triggerClassName,
  className = "",
}: {
  /** The button's accessible name (e.g. "Project actions"). */
  label: string;
  trigger: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
  /** "above" for a button at the bottom of the screen (the account chip). */
  side?: "below" | "above";
  /** Replaces the icon-button look (e.g. a full-width account chip). */
  triggerClassName?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus();
    function outside(event: PointerEvent) {
      if (!list.current?.contains(event.target as Node) && !button.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  function close(focusButton = true) {
    setOpen(false);
    if (focusButton) button.current?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    const entries = [...(list.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])];
    const index = entries.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") {
      close(false);
    } else {
      const next = menuIndex(event.key, index, entries.length);
      if (next !== null) {
        event.preventDefault();
        entries[next]?.focus();
      }
    }
  }

  return (
    <div className={`relative ${className}`}>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className={
          triggerClassName ??
          "inline-flex size-9 items-center justify-center rounded-control text-muted transition-colors hover:bg-white/[0.06] hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:size-11 [&_svg]:size-4"
        }
      >
        {trigger}
      </button>
      {open ? (
        <div
          ref={list}
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onKeyDown}
          className={`absolute z-50 min-w-48 animate-dialog-in rounded-block border border-border-strong bg-surface-2 p-1 shadow-raised ${
            side === "above" ? "bottom-full mb-1" : "top-full mt-1"
          } ${align === "end" ? "right-0" : "left-0"}`}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                // Focus goes back to the menu button first, so a dialog opened by the item
                // returns focus there when it closes.
                close();
                item.onSelect();
              }}
              className={`flex min-h-9 w-full items-center gap-2.5 rounded-control px-2.5 text-left text-sm transition-colors outline-none focus-visible:bg-white/[0.08] disabled:cursor-not-allowed disabled:text-subtle pointer-coarse:min-h-11 ${
                item.tone === "danger" ? "text-rose-200 hover:bg-danger/15 focus-visible:bg-danger/15" : "text-foreground hover:bg-white/[0.06]"
              }`}
            >
              {item.icon ? <item.icon aria-hidden="true" className="size-4 shrink-0" /> : null}
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
