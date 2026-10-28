"use client";

import { useId, useState } from "react";
import { inputBase } from "@/components/ui/input-styles";
import { normalizeHex } from "@/lib/brand-rules";

/**
 * A colour: the system colour picker (keyboard accessible, labelled) next to a labelled hex
 * field that is validated as you type. Only `#RRGGBB` ever leaves this field. Optional colours
 * can be cleared.
 */
export function ColorField({
  label,
  hint,
  value,
  onChange,
  optional = false,
  status,
  fallback,
}: {
  label: string;
  hint?: string;
  value: string | null;
  onChange: (value: string | null) => void;
  optional?: boolean;
  /** A short note under the field (e.g. readability), shown with an icon-free text. */
  status?: { tone: "ok" | "warn"; text: string } | null;
  /** What applies while an optional colour is empty (shown in the swatch). */
  fallback?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState(value ?? "");
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    // A new value from outside (a reset or another brand): show it.
    setSynced(value);
    setDraft(value ?? "");
  }
  const invalid = draft.trim() !== "" && normalizeHex(draft) === null;
  const describedBy = [hint ? `${id}-hint` : null, invalid ? `${id}-error` : null, status ? `${id}-status` : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={`${id}-hex`} className="block text-sm font-medium text-foreground">
        {label}
        {optional ? <span className="font-normal text-subtle"> (optional)</span> : null}
      </label>
      {hint ? (
        <p id={`${id}-hint`} className="text-caption text-subtle">
          {hint}
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} picker`}
          value={normalizeHex(draft) ?? value ?? fallback ?? "#000000"}
          onChange={(event) => {
            const hex = normalizeHex(event.target.value);
            setDraft(hex ?? event.target.value);
            if (hex) onChange(hex);
          }}
          className="size-11 shrink-0 cursor-pointer rounded-lg border border-border-strong bg-transparent p-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
        <input
          id={`${id}-hex`}
          type="text"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          maxLength={7}
          placeholder={optional ? (fallback ? `Same as primary` : "None") : "#FF3A72"}
          value={draft}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          onChange={(event) => {
            const text = event.target.value;
            setDraft(text);
            if (!text.trim() && optional) onChange(null);
            const hex = normalizeHex(text);
            if (hex) onChange(hex);
          }}
          onBlur={() => {
            const hex = normalizeHex(draft);
            if (hex) setDraft(hex);
          }}
          className={`${inputBase} h-11 w-36 px-3 font-mono text-sm placeholder:font-sans`}
        />
        {optional && value ? (
          <button
            type="button"
            onClick={() => {
              setDraft("");
              onChange(null);
            }}
            className="min-h-11 rounded-md px-2 text-small text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
          >
            Clear<span className="sr-only"> {label.toLowerCase()}</span>
          </button>
        ) : null}
      </div>
      {invalid ? (
        <p id={`${id}-error`} className="text-sm text-rose-400">
          Use a hex colour like #FF3A72.
        </p>
      ) : null}
      {status ? (
        <p id={`${id}-status`} className={`text-caption ${status.tone === "ok" ? "text-subtle" : "text-amber-200"}`}>
          {status.text}
        </p>
      ) : null}
    </div>
  );
}
