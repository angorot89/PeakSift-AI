"use client";

import type { LucideIcon } from "lucide-react";
import { useRef } from "react";
import { tabKeyIndex } from "@/lib/menu-keys";

export type TabItem<K extends string> = {
  key: K;
  label: string;
  icon: LucideIcon;
  /** A small mark after the label: "on" (something is set) or "attention" (it blocks rendering). */
  mark?: "on" | "attention" | null;
};

const MARK_TEXT = { on: " (in use)", attention: " (needs attention)" } as const;

/**
 * An ARIA tab list of tool groups (icon over label). Arrow keys, Home and End move between
 * tabs and select them; only the selected tab is in the Tab order.
 */
export function ToolTabs<K extends string>({
  items,
  value,
  onChange,
  label,
  idBase,
}: {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  idBase: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 rounded-block border border-border bg-surface/80 p-1">
      {items.map((item, index) => {
        const selected = item.key === value;
        const Icon = item.icon;
        return (
          <button
            key={item.key}
            ref={(node) => {
              refs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${idBase}-tab-${item.key}`}
            aria-selected={selected}
            aria-controls={`${idBase}-panel-${item.key}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.key)}
            onKeyDown={(event) => {
              const next = tabKeyIndex(event.key, index, items.length);
              if (next === null) return;
              event.preventDefault();
              onChange(items[next].key);
              refs.current[next]?.focus();
            }}
            className={`relative flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-control px-1 text-caption font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${
              selected
                ? "bg-accent/[0.13] text-foreground shadow-[inset_0_0_0_1px_rgb(249_115_22/0.45)]"
                : "text-muted hover:bg-surface-3/70 hover:text-foreground"
            }`}
          >
            <Icon aria-hidden="true" className={`size-4 ${selected ? "text-accent-soft" : ""}`} />
            <span className="max-w-full truncate">{item.label}</span>
            {item.mark ? (
              <>
                <span
                  aria-hidden="true"
                  className={`absolute top-1.5 right-1.5 size-1.5 rounded-full ${item.mark === "attention" ? "bg-warning" : "bg-accent"}`}
                />
                <span className="sr-only">{MARK_TEXT[item.mark]}</span>
              </>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** Props for the panel of one tab; panels stay mounted (hidden) so their state survives. */
export function toolPanelProps(idBase: string, key: string, active: boolean) {
  return {
    role: "tabpanel" as const,
    id: `${idBase}-panel-${key}`,
    "aria-labelledby": `${idBase}-tab-${key}`,
    hidden: !active,
    tabIndex: 0,
  };
}
