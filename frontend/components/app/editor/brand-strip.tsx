"use client";

import { Palette, Shapes } from "lucide-react";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/inline-alert";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { createTemplate, getEditSection, updateTemplate, type TemplateSettings } from "@/lib/brand";
import { CORNER_LABELS, SIZE_LABELS, type LogoCorner, type LogoSize } from "@/lib/brand-rules";
import type { EditOrigin } from "@/lib/edits";

/** One brand element of this Short: its name, a colour swatch when it has one, and its value. */
function ElementRow({ label, value, swatch = null }: { label: string; value: string; swatch?: string | null }) {
  return (
    <li className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className="flex min-w-0 items-center gap-2 text-right text-foreground">
        {swatch ? <span aria-hidden="true" className="size-4 shrink-0 rounded-full ring-1 ring-white/20" style={{ background: swatch }} /> : null}
        <span className="truncate">{value}</span>
      </span>
    </li>
  );
}

/** Where this Short's settings came from, for the editor's header: read-only, never a control. */
export function OriginChips({ origin, brand }: { origin: EditOrigin | null; brand: Record<string, unknown> | null }) {
  const brandName = typeof brand?.name === "string" ? brand.name : null;
  const chip = "inline-flex min-h-9 max-w-full items-center gap-2 rounded-control border border-border bg-surface/80 px-3 text-small";
  return (
    <span className="flex flex-wrap gap-2">
      <span className={chip}>
        <Shapes aria-hidden="true" className="size-4 shrink-0 text-subtle" />
        <span className="text-subtle">Template:</span>
        <span className="truncate font-medium text-foreground">{origin?.template ? origin.template.name : "None"}</span>
      </span>
      <span className={chip}>
        <Palette aria-hidden="true" className="size-4 shrink-0 text-subtle" />
        <span className="text-subtle">Brand:</span>
        <span className="truncate font-medium text-foreground">{brandName ?? "None"}</span>
      </span>
    </span>
  );
}

/**
 * This Short's brand and where its settings came from ("Template: Punchy Gaming · Brand: Amine
 * Clips"). Changes here affect this Short only. Templates change only through an explicit
 * "Save as template" / "Update …" — never silently.
 */
export function BrandPanel({
  brand,
  origin,
  onBrand,
  templateSettings,
}: {
  brand: Record<string, unknown> | null;
  origin: EditOrigin | null;
  onBrand: (brand: Record<string, unknown> | null, origin: EditOrigin | null) => void;
  /** The editor's settings, as a template would hold them (computed when saving). */
  templateSettings: () => TemplateSettings;
}) {
  const toast = useToast();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<"new" | "update" | null>(null);
  const [name, setName] = useState("");

  const name_ = typeof brand?.name === "string" ? brand.name : null;

  async function addBrand() {
    setBusy(true);
    setError(null);
    try {
      const section = await getEditSection(origin?.template?.id ?? null);
      if (!section.brand) {
        setError("You have no brand yet. Create one in Brand Studio.");
        return;
      }
      onBrand(section.brand, { ...(section.template ? { template: section.template } : {}), brand: { name: String(section.brand.name) } });
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!name.trim() && saving === "new") return;
    setBusy(true);
    setError(null);
    try {
      const config = templateSettings();
      if (saving === "update" && origin?.template) {
        await updateTemplate(origin.template.id, { config });
        toast(`“${origin.template.name}” updated for new Shorts`);
      } else {
        await createTemplate({ name: name.trim(), description: "", recipe: null, brand_profile_id: null, config });
        toast(`Template “${name.trim()}” saved`);
      }
      setSaving(null);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  const logo = brand?.logo as { corner?: LogoCorner; size?: LogoSize } | undefined;
  const emphasis = typeof brand?.caption_emphasis === "string" ? brand.caption_emphasis : null;
  const accent = typeof brand?.hook_accent === "string" ? brand.hook_accent : null;
  const card = brand?.end_card as { seconds?: number; background?: string; text?: string } | undefined;

  return (
    <div className="space-y-6">
      <section aria-labelledby={`${id}-from`} className="rounded-block border border-border bg-surface-2/60 p-4">
        <h3 id={`${id}-from`} className="text-title">
          This Short
        </h3>
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted">Template</dt>
          <dd className="truncate font-medium text-foreground">{origin?.template ? origin.template.name : "None"}</dd>
          <dt className="text-muted">Brand</dt>
          <dd className="truncate font-medium text-foreground">{name_ ?? "No brand"}</dd>
        </dl>
        <p className="mt-3 text-caption text-subtle">Changes here apply to this Short only.</p>
      </section>

      <section aria-labelledby={`${id}-elements`}>
        <h3 id={`${id}-elements`} className="text-title">
          Brand elements
        </h3>
        {brand ? (
          <>
            <ul className="mt-3 divide-y divide-border rounded-block border border-border">
              <ElementRow label="Logo" value={logo?.corner ? `${CORNER_LABELS[logo.corner]} · ${SIZE_LABELS[logo.size ?? "small"]}` : "Not shown"} />
              <ElementRow label="Caption emphasis" swatch={emphasis} value={emphasis ?? "Not used"} />
              <ElementRow label="Hook accent" swatch={accent} value={accent ? `${accent} (Boxed hook)` : "Not used"} />
              <ElementRow
                label="End card"
                swatch={card?.seconds ? (card.background ?? null) : null}
                value={card?.seconds ? `${card.seconds} s${card.text ? ` · “${card.text}”` : ""}` : "Off"}
              />
            </ul>
            <p className="mt-2 text-caption text-pretty text-subtle">
              Edit colours and the logo in Brand Studio; this Short keeps the brand it was made with.
            </p>
          </>
        ) : (
          <p className="mt-3 rounded-block border border-dashed border-border-strong p-4 text-sm text-pretty text-muted">
            No brand on this Short. Add yours to show your logo, colours and end card.
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {brand ? (
            <Button size="sm" variant="secondary" onClick={() => onBrand(null, origin?.template ? { template: origin.template } : null)}>
              Remove branding
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => void addBrand()} disabled={busy}>
              <Palette aria-hidden="true" />
              Add my brand
            </Button>
          )}
        </div>
      </section>

      <section aria-labelledby={`${id}-templates`} className="border-t border-border pt-5">
        <h3 id={`${id}-templates`} className="text-title">
          Templates
        </h3>
        <p className="mt-1 text-sm text-pretty text-muted">
          Reuse how this Short is edited. Saving is always your choice, and Shorts you already made never change.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => { setName(""); setSaving("new"); }}>
            <Shapes aria-hidden="true" /> Save as template
          </Button>
          {origin?.template ? (
            <Button size="sm" variant="secondary" onClick={() => setSaving("update")}>
              Update “{origin.template.name}”
            </Button>
          ) : null}
        </div>
      </section>
      {error ? <InlineAlert title="That didn't work">{error}</InlineAlert> : null}
      <Dialog
        open={saving !== null}
        onClose={() => setSaving(null)}
        title={saving === "update" ? `Update “${origin?.template?.name ?? ""}”?` : "Save as template"}
        description={
          saving === "update"
            ? "Shorts you make from now on start from these settings. Shorts you already made keep theirs."
            : "Saves how this Short is edited — captions, hook style, framing, B-roll amount, sound levels. Not its words, music or visuals."
        }
        footer={
          <>
            <Button variant="secondary" onClick={() => setSaving(null)}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={busy || (saving === "new" && !name.trim())}>
              {saving === "update" ? "Update template" : "Save template"}
            </Button>
          </>
        }
      >
        {saving === "new" ? (
          <Field id={`${id}-template-name`} label="Template name" value={name} maxLength={60} data-autofocus onChange={(e) => setName(e.target.value)} />
        ) : (
          <p className="text-sm text-muted">Its brand, name and starting style stay as they are.</p>
        )}
      </Dialog>
    </div>
  );
}
