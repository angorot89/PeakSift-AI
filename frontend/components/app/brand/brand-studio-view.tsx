"use client";

import { Clapperboard, Palette, Plus, Shapes, Star } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/app/page-header";
import { BrandPreview, type PreviewEdit } from "@/components/app/brand/brand-preview";
import { ColorField } from "@/components/app/brand/color-field";
import { LogoPicker } from "@/components/app/brand/logo-picker";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/inline-alert";
import { SectionHeader } from "@/components/ui/section-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import {
  createBrand,
  deleteBrand,
  getBrandLayout,
  listBrands,
  logoUrl,
  updateBrand,
  type Brand,
  type BrandInput,
  type BrandLayout,
  type BrandLogo,
} from "@/lib/brand";
import { CORNER_LABELS, emphasisReadable, SIZE_LABELS, type LogoCorner, type LogoSize } from "@/lib/brand-rules";
import { getCaptionStyles, type CaptionStyles } from "@/lib/captions";

type Draft = {
  name: string;
  primary: string;
  accent: string | null;
  emphasis: string | null;
  logo: BrandLogo | null;
  corner: LogoCorner;
  size: LogoSize;
  endText: string;
  isDefault: boolean;
};

const NEW_DRAFT: Draft = {
  name: "",
  primary: "#F43F5E",
  accent: null,
  emphasis: null,
  logo: null,
  corner: "top_right",
  size: "small",
  endText: "",
  isDefault: true,
};

// What Brand Studio previews with: the brand on a typical Short (the template decides the rest).
const SAMPLE_EDIT: PreviewEdit = {
  captions: true,
  preset: "punch",
  captionPosition: "bottom",
  hook: true,
  hookStyle: "boxed",
  hookPosition: "top",
  hookSeconds: 2,
  logo: true,
  endCard: true,
  endCardSeconds: 2,
};

const fromBrand = (brand: Brand): Draft => ({
  name: brand.name,
  primary: brand.primary_color,
  accent: brand.accent_color,
  emphasis: brand.caption_emphasis_color,
  logo: brand.logo,
  corner: brand.logo_position,
  size: brand.logo_size,
  endText: brand.end_card_text ?? "",
  isDefault: brand.is_default,
});

const toInput = (draft: Draft): BrandInput => ({
  name: draft.name.trim(),
  primary_color: draft.primary,
  accent_color: draft.accent,
  caption_emphasis_color: draft.emphasis,
  logo_asset_id: draft.logo?.id ?? null,
  logo_position: draft.corner,
  logo_size: draft.size,
  end_card_text: draft.endText.trim() || null,
});

const same = (a: Draft, b: Draft) => JSON.stringify(toInput(a)) === JSON.stringify(toInput(b)) && a.isDefault === b.isDefault;

/** The three words creators need, explained once at the top. */
function Glossary() {
  const items: { icon: typeof Palette; title: string; text: string }[] = [
    { icon: Palette, title: "Brand", text: "How your Shorts look: colours, logo, end card." },
    { icon: Shapes, title: "Template", text: "How your Shorts are edited: captions, hook, B-roll, sound." },
    { icon: Clapperboard, title: "Each Short", text: "Starts from them. You can still change anything." },
  ];
  return (
    <ul className="mb-8 grid gap-3 sm:grid-cols-3" aria-label="How Brand Studio works">
      {items.map(({ icon: Icon, title, text }) => (
        <li key={title} className="flex gap-3 rounded-xl border border-border bg-surface/60 p-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-accent-soft">
            <Icon aria-hidden="true" className="size-[18px]" />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium text-foreground">{title}</span>
            <span className="block text-small text-muted">{text}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Row({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium text-foreground">{label}</p>
      {children}
      {hint ? <p className="text-caption text-subtle">{hint}</p> : null}
    </div>
  );
}

export function BrandStudioView({ templates }: { templates?: ReactNode }) {
  const toast = useToast();
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [spec, setSpec] = useState<CaptionStyles | null>(null);
  const [layout, setLayout] = useState<BrandLayout | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(NEW_DRAFT);
  const [saved, setSaved] = useState<Draft>(NEW_DRAFT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const pick = useCallback((brand: Brand | null) => {
    const next = brand ? fromBrand(brand) : { ...NEW_DRAFT };
    setSelected(brand ? brand.id : "new");
    setDraft(next);
    setSaved(next);
    setError(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listBrands(), getCaptionStyles(), getBrandLayout()])
      .then(([list, styles, numbers]) => {
        if (cancelled) return;
        setBrands(list);
        setSpec(styles);
        setLayout(numbers);
        if (list.length) pick(list[0]);
      })
      .catch((failure: unknown) => !cancelled && setLoadError(errorMessage(failure)));
    return () => {
      cancelled = true;
    };
  }, [pick]);

  const dirty = selected !== null && !same(draft, saved);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const preview = useMemo(
    () => ({
      name: draft.name.trim() || "Your brand",
      primary: draft.primary,
      accent: draft.accent,
      emphasis: draft.emphasis,
      logoUrl: draft.logo ? logoUrl(draft.logo) : null,
      corner: draft.corner,
      size: draft.size,
      endText: draft.endText.trim() || null,
    }),
    [draft],
  );

  async function save() {
    if (!draft.name.trim()) {
      setError("Give your brand a name.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const input = toInput(draft);
      const result =
        selected === "new"
          ? await createBrand({ ...input, is_default: draft.isDefault })
          : await updateBrand(selected!, { ...input, is_default: draft.isDefault });
      const list = await listBrands();
      setBrands(list);
      pick(list.find((b) => b.id === result.id) ?? result);
      toast("Brand saved");
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!selected || selected === "new") return;
    try {
      await deleteBrand(selected);
      const list = await listBrands();
      setBrands(list);
      setConfirmDelete(false);
      if (list.length) pick(list[0]);
      else {
        setSelected(null);
      }
      toast("Brand deleted");
    } catch (failure) {
      setConfirmDelete(false);
      setError(errorMessage(failure));
    }
  }

  const emphasisStatus = draft.emphasis
    ? emphasisReadable(draft.emphasis)
      ? { tone: "ok" as const, text: "Readable on captions: the spoken word uses it." }
      : { tone: "warn" as const, text: "Too dark to read as caption text, so captions keep their own colour. It still works as an accent." }
    : null;

  return (
    <div>
      <PageHeader
        title="Brand Studio"
        description="Set up how your Shorts look and how they're edited once — every new Short can start from it."
      />
      <Glossary />
      {loadError ? <InlineAlert title="Brand Studio couldn't load">{loadError}</InlineAlert> : null}

      <section aria-labelledby="brand-heading" className="mb-12">
        <SectionHeader
          id="brand-heading"
          title="Your brand"
          description="How your Shorts look. Used by your templates; changing it never alters Shorts you already made."
          actions={
            brands && brands.length > 0 ? (
              <Button variant="secondary" size="sm" onClick={() => pick(null)} disabled={selected === "new"}>
                <Plus aria-hidden="true" className="size-4" /> New brand
              </Button>
            ) : null
          }
        />
        {brands === null && !loadError ? <Skeleton className="h-96 rounded-2xl" /> : null}
        {brands !== null && brands.length === 0 && selected === null ? (
          <EmptyState
            icon={Palette}
            title="No brand yet"
            description="Choose your colours and logo once. Your templates and Shorts can then use them."
            action={<Button onClick={() => pick(null)}>Create your brand</Button>}
          />
        ) : null}
        {brands !== null && brands.length > 1 && selected !== "new" ? (
          <div className="mb-4">
            <SegmentedControl
              label="Brand"
              options={brands.map((b) => ({ value: b.id, label: `${b.name}${b.is_default ? " (default)" : ""}` }))}
              value={selected ?? brands[0].id}
              onChange={(id) => pick(brands.find((b) => b.id === id) ?? null)}
            />
          </div>
        ) : null}

        {selected !== null && spec && layout ? (
          <Card className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <form
              className="min-w-0 space-y-6"
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
              aria-label={selected === "new" ? "New brand" : `Brand ${saved.name}`}
            >
              <Field
                id="brand-name"
                label="Brand name"
                value={draft.name}
                maxLength={60}
                placeholder="e.g. Amine Clips"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
              <div className="grid gap-6 sm:grid-cols-2">
                <ColorField label="Primary colour" hint="Your end card's background." value={draft.primary} onChange={(v) => v && setDraft({ ...draft, primary: v })} />
                <ColorField label="Accent colour" hint="The Boxed hook's label. Defaults to the primary colour." optional value={draft.accent} fallback={draft.primary} onChange={(v) => setDraft({ ...draft, accent: v })} />
              </div>
              <ColorField
                label="Caption emphasis"
                hint="The colour of the word being spoken in word-by-word captions."
                optional
                value={draft.emphasis}
                onChange={(v) => setDraft({ ...draft, emphasis: v })}
                status={emphasisStatus}
              />
              <Row label="Logo" hint="From your images. Transparent PNGs look best. Logos keep their shape and stay inside the safe area.">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 truncate text-sm text-muted">{draft.logo ? draft.logo.name : "No logo"}</span>
                  <Button type="button" variant="secondary" size="sm" onClick={() => setPicker(true)}>
                    {draft.logo ? "Change logo" : "Choose logo"}
                  </Button>
                  {draft.logo ? (
                    <Button type="button" variant="ghost" size="sm" onClick={() => setDraft({ ...draft, logo: null })}>
                      Remove
                    </Button>
                  ) : null}
                </div>
              </Row>
              {draft.logo ? (
                <div className="grid gap-6 sm:grid-cols-2">
                  <Row label="Corner">
                    <SegmentedControl
                      label="Logo corner"
                      size="sm"
                      options={(Object.keys(CORNER_LABELS) as LogoCorner[]).map((c) => ({ value: c, label: CORNER_LABELS[c] }))}
                      value={draft.corner}
                      onChange={(corner) => setDraft({ ...draft, corner })}
                    />
                  </Row>
                  <Row label="Size">
                    <SegmentedControl
                      label="Logo size"
                      size="sm"
                      options={(Object.keys(SIZE_LABELS) as LogoSize[]).map((s) => ({ value: s, label: SIZE_LABELS[s] }))}
                      value={draft.size}
                      onChange={(size) => setDraft({ ...draft, size })}
                    />
                  </Row>
                </div>
              ) : null}
              <Field
                id="brand-end-text"
                label="End-card line (optional)"
                value={draft.endText}
                maxLength={40}
                placeholder="e.g. Follow for more"
                onChange={(event) => setDraft({ ...draft, endText: event.target.value })}
              />
              <label className="flex min-h-11 items-center gap-3 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={draft.isDefault}
                  onChange={(event) => setDraft({ ...draft, isDefault: event.target.checked })}
                  className="size-5 accent-[var(--color-accent)]"
                />
                <span className="inline-flex items-center gap-1.5">
                  <Star aria-hidden="true" className="size-4 text-accent-soft" /> Use as my default brand
                </span>
              </label>
              {error ? <InlineAlert title="That didn't work">{error}</InlineAlert> : null}
              <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
                <Button type="submit" disabled={saving || (!dirty && selected !== "new")}>
                  {saving ? "Saving…" : selected === "new" ? "Create brand" : "Save brand"}
                </Button>
                <p className="text-caption text-subtle" role="status">
                  {dirty ? "Unsaved changes" : selected === "new" ? "" : "Saved"}
                </p>
                {selected !== "new" ? (
                  <Button type="button" variant="ghost" size="sm" className="ml-auto text-rose-300" onClick={() => setConfirmDelete(true)}>
                    Delete brand
                  </Button>
                ) : brands && brands.length > 0 ? (
                  <Button type="button" variant="ghost" size="sm" className="ml-auto" onClick={() => pick(brands[0])}>
                    Cancel
                  </Button>
                ) : null}
              </div>
            </form>
            <div className="lg:sticky lg:top-6 lg:self-start">
              <BrandPreview spec={spec} layout={layout} brand={preview} edit={SAMPLE_EDIT} />
            </div>
          </Card>
        ) : null}
      </section>

      {templates}

      <LogoPicker
        open={picker}
        onClose={() => setPicker(false)}
        selected={draft.logo?.id ?? null}
        onSelect={(logo) => setDraft({ ...draft, logo })}
      />
      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={`Delete “${saved.name}”?`}
        description="Shorts you already made keep their look. Templates using this brand will have no brand."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Keep it
            </Button>
            <Button variant="danger" onClick={() => void remove()}>
              Delete brand
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">This can&apos;t be undone.</p>
      </Dialog>
    </div>
  );
}
