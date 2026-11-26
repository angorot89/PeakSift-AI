"use client";

import { Check } from "lucide-react";
import type { ReactNode } from "react";
import {
  LAYOUT_OPTIONS,
  POSITION_OPTIONS,
  type CaptionPosition,
  type PickableLayout,
} from "@/lib/edits";

/** Section label + optional helper for one group of editor controls. */
export function ControlGroup({
  legend,
  hint,
  children,
  disabled = false,
}: {
  legend: string;
  hint?: string;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <fieldset disabled={disabled} className="min-w-0 space-y-2.5 transition-opacity disabled:opacity-40">
      <legend className="mb-2.5 flex w-full items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{legend}</span>
        {hint ? <span className="text-xs text-subtle">{hint}</span> : null}
      </legend>
      {children}
    </fieldset>
  );
}

/** A radio rendered as a selectable card. Real input → arrow keys, focus and labels work. */
export function OptionCard({
  name,
  value,
  checked,
  onChange,
  children,
  label,
  className = "",
  badge = true,
  disabled = false,
}: {
  name: string;
  value: string;
  checked: boolean;
  onChange: () => void;
  children: ReactNode;
  label: string;
  className?: string;
  /** Corner check mark; cards with text near the corner show an inline check instead. */
  badge?: boolean;
  disabled?: boolean;
}) {
  return (
    <label
      className={`group relative flex flex-col rounded-block border bg-surface-2 ${disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"} transition-[border-color,background-color,box-shadow] duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
        checked
          ? "border-accent/70 bg-accent/[0.06] shadow-[0_0_0_1px_var(--accent)]"
          : "border-border hover:border-border-strong hover:bg-surface-3"
      } ${className}`}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="sr-only"
        aria-label={label}
      />
      {/* A check mark keeps the selection visible without relying on colour. */}
      {badge ? (
      <span
        aria-hidden="true"
        className={`absolute top-2 right-2 flex size-4 items-center justify-center rounded-full bg-accent text-background transition-[opacity,transform] duration-150 ${
          checked ? "scale-100 opacity-100" : "scale-75 opacity-0"
        }`}
      >
        <Check className="size-2.5" strokeWidth={3.5} />
      </span>
      ) : null}
      {children}
    </label>
  );
}

/** Miniature 9:16 diagram of a layout (what is filled, what is cropped). */
function LayoutDiagram({ layout }: { layout: PickableLayout }) {
  return (
    <span aria-hidden="true" className="relative block h-14 w-8 overflow-hidden rounded-[5px] border border-white/15 bg-black">
      {layout === "smart_reframe" ? (
        <>
          <span className="absolute inset-0 bg-gradient-to-b from-subtle/45 to-subtle/25" />
          <span className="absolute top-[30%] left-[58%] size-2.5 rounded-full border border-white/80 bg-white/30" />
          <span className="absolute top-[18%] left-[32%] h-[36%] w-[58%] rounded-[3px] border border-dashed border-white/70" />
        </>
      ) : layout === "center_crop" ? (
        <>
          <span className="absolute inset-0 bg-gradient-to-b from-subtle/55 to-subtle/30" />
          <span className="absolute inset-y-0 -left-2 w-2 border-r border-dashed border-white/40" />
        </>
      ) : layout === "blur_background" ? (
        <>
          <span className="absolute inset-0 bg-subtle/25 blur-[2px]" />
          <span className="absolute inset-x-0 top-1/2 h-[30%] -translate-y-1/2 bg-gradient-to-b from-subtle/70 to-subtle/45" />
        </>
      ) : (
        <>
          <span className="absolute inset-0 bg-[#111113]" />
          <span className="absolute inset-x-0 top-1/2 h-[30%] -translate-y-1/2 bg-gradient-to-b from-subtle/70 to-subtle/45" />
        </>
      )}
    </span>
  );
}

export function LayoutPicker({
  value,
  onChange,
  name,
}: {
  value: PickableLayout;
  onChange: (v: PickableLayout) => void;
  name: string;
}) {
  return (
    <ControlGroup legend="Layout">
      <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-2">
        {LAYOUT_OPTIONS.map((option) => (
          <OptionCard
            key={option.value}
            name={name}
            value={option.value}
            label={`${option.label}: ${option.hint}`}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            className="flex-row items-center gap-3 px-3 py-2.5 text-left"
          >
            <LayoutDiagram layout={option.value} />
            <span className="min-w-0 pr-3">
              <span className="block text-small leading-tight font-medium text-foreground">{option.label}</span>
              <span className="mt-0.5 block text-caption leading-snug text-subtle">{option.hint}</span>
            </span>
          </OptionCard>
        ))}
      </div>
    </ControlGroup>
  );
}

export function CaptionSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-block border border-border bg-surface-2 px-3.5 py-3">
      <div className="min-w-0">
        <p id="captions-switch-label" className="text-sm font-medium text-foreground">
          Captions
        </p>
        <p id="captions-switch-hint" className="text-xs text-subtle">
          Burned in, with the spoken word emphasised
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby="captions-switch-label"
        aria-describedby="captions-switch-hint"
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          checked ? "border-accent bg-accent" : "border-border-strong bg-surface-3"
        }`}
      >
        <span className="sr-only">{checked ? "On" : "Off"}</span>
        <span
          aria-hidden="true"
          className={`inline-block size-[18px] rounded-full bg-white shadow transition-transform duration-150 ${
            checked ? "translate-x-[22px]" : "translate-x-[2px]"
          }`}
        />
      </button>
    </div>
  );
}

export function InlineCheck({ on }: { on: boolean }) {
  return on ? (
    <span aria-hidden="true" className="flex size-4 shrink-0 items-center justify-center rounded-full bg-accent text-background">
      <Check className="size-2.5" strokeWidth={3.5} />
    </span>
  ) : null;
}

function PositionGlyph({ position }: { position: CaptionPosition }) {
  const place = position === "top" ? "top-[16%]" : position === "center" ? "top-1/2 -translate-y-1/2" : "bottom-[18%]";
  return (
    <span aria-hidden="true" className="relative block h-9 w-5 rounded-[4px] border border-white/25 bg-black/40">
      <span className={`absolute inset-x-[3px] h-[3px] rounded-full bg-current ${place}`} />
    </span>
  );
}

export function PositionPicker({
  value,
  onChange,
  name,
  disabled,
  taken,
}: {
  value: CaptionPosition;
  onChange: (v: CaptionPosition) => void;
  name: string;
  disabled: boolean;
  /** A position the hook already uses (captions and hook never overlap). */
  taken?: CaptionPosition | null;
}) {
  return (
    <ControlGroup legend="Caption position" hint={taken ? `${taken === "top" ? "Top" : "Center"} is used by the hook` : undefined} disabled={disabled}>
      <div className="grid grid-cols-3 gap-2">
        {POSITION_OPTIONS.map((option) => (
          <OptionCard
            key={option.value}
            name={name}
            value={option.value}
            label={option.label}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            disabled={taken === option.value}
            className={`flex-row items-center justify-center gap-2 px-2 py-2.5 ${value === option.value ? "text-accent-soft" : "text-muted"}`}
            badge={false}
          >
            <PositionGlyph position={option.value} />
            <span className="text-small font-medium text-foreground">{option.label}</span>
            <InlineCheck on={value === option.value} />
          </OptionCard>
        ))}
      </div>
    </ControlGroup>
  );
}
