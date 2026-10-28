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
import type { EditOrigin } from "@/lib/edits";

/**
 * This Short's brand and where its settings came from ("Template: Punchy Gaming · Brand: Amine
 * Clips"). Changes here affect this Short only. Templates change only through an explicit
 * "Save as template" / "Update …" — never silently.
 */
export function BrandStrip({
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
  const endCard = brand?.end_card as { seconds?: number } | undefined;
  const parts = [
    origin?.template ? `Template: ${origin.template.name}` : null,
    name_ ? `Brand: ${name_}` : "No brand",
  ].filter(Boolean);

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

  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-xs">
      <p className="flex items-start gap-2 text-muted">
        <Palette aria-hidden="true" className="mt-px size-3.5 shrink-0 text-accent-soft" />
        <span className="min-w-0 break-words">
          <span className="text-foreground">{parts.join(" · ")}</span>
          {endCard?.seconds ? <> · end card +{endCard.seconds}s</> : null}
          <span className="block text-subtle">Changes here apply to this Short only.</span>
        </span>
      </p>
      <div className="flex flex-wrap gap-1.5 pl-5.5">
        {brand ? (
          <Button size="sm" variant="ghost" onClick={() => onBrand(null, origin?.template ? { template: origin.template } : null)}>
            Remove branding
          </Button>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => void addBrand()} disabled={busy}>
            Add my brand
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => { setName(""); setSaving("new"); }}>
          <Shapes aria-hidden="true" /> Save as template
        </Button>
        {origin?.template ? (
          <Button size="sm" variant="ghost" onClick={() => setSaving("update")}>
            Update “{origin.template.name}”
          </Button>
        ) : null}
      </div>
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
