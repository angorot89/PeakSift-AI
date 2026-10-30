"use client";

import { Clapperboard, ImageIcon, Palette, Plus, RotateCcw, Shapes, Star } from "lucide-react";
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
import { StatusPill } from "@/components/ui/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import {
  createBrand,
  deleteBrand,
  getBrandLayout,
  listBrands,
  listTemplates,
  logoUrl,
  updateBrand,
  type Brand,
  type BrandInput,
  type BrandLayout,
  type BrandLogo,
} from "@/lib/brand";
import { CORNER_LABELS, emphasisReadable, SIZE_LABELS, textOn, type LogoCorner, type LogoSize } from "@/lib/brand-rules";
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
        <li key={title} className="flex gap-3 rounded-block border border-border bg-surface/60 p-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-accent/12 text-accent-soft">
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

/** One brand in the library: its colour and logo, its name, whether it is the default, and how
 * many templates use it. Pressing it opens it in the editor below. */
function BrandCard({ brand, templates, selected, onPick }: { brand: Brand; templates: number | null; selected: boolean; onPick: () => void }) {
  return (
    <li className="min-w-0">
      <button
        type="button"
        aria-pressed={selected}
        onClick={onPick}
        className={`flex min-h-16 w-full items-center gap-3 rounded-block border p-3 text-left transition-[border-color,background-color] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          selected ? "border-accent/55 bg-accent/[0.08]" : "border-border bg-surface-2/50 hover:border-border-strong hover:bg-surface-2"
        }`}
      >
        <span
          aria-hidden="true"
          className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-block ring-1 ring-white/15"
          style={{ background: brand.primary_color }}
        >
          {brand.logo ? (
            // eslint-disable-next-line @next/next/no-img-element -- a private, session-authenticated image
            <img src={logoUrl(brand.logo)} alt="" className="size-9 object-contain" />
          ) : (
            <span className="text-lg font-bold" style={{ color: textOn(brand.primary_color) }}>
              {brand.name.charAt(0).toUpperCase()}
            </span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">{brand.name}</span>
            {brand.is_default ? <StatusPill tone="accent">Default</StatusPill> : null}
          </span>
          {templates !== null ? (
            <span className="mt-0.5 block text-caption text-subtle">
              {templates} template{templates === 1 ? "" : "s"}
            </span>
          ) : null}
        </span>
      </button>
    </li>
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
  const [usage, setUsage] = useState<Record<string, number> | null>(null);

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
    // How many templates use each brand (the library shows it; nothing depends on it).
    listTemplates()
      .then((list) => {
        if (cancelled) return;
        const counts: Record<string, number> = {};
        for (const template of list) {
          if (template.brand) counts[template.brand.id] = (counts[template.brand.id] ?? 0) + 1;
        }
        setUsage(counts);
      })
      .catch(() => undefined);
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
        size="hero"
        title={
          <>
            Brand <span className="text-accent-soft">Studio</span>
          </>
        }
        description="How your Shorts look and how they're edited — set it up once, and every new Short can start from it."
      />
      <Glossary />
      {loadError ? <InlineAlert title="Brand Studio couldn't load">{loadError}</InlineAlert> : null}

      <section aria-labelledby="brand-heading" className="mb-12">
        {brands === null && !loadError ? <Skeleton className="h-96 rounded-card" /> : null}
        {brands !== null && brands.length === 0 && selected === null ? (
          <>
            <SectionHeader id="brand-heading" title="Your brand" description="How your Shorts look. Used by your templates; changing it never alters Shorts you already made." />
            <EmptyState
              icon={Palette}
              title="No brand yet"
              description="Choose your colours and logo once. Your templates and Shorts can then use them."
              action={<Button onClick={() => pick(null)}>Create your brand</Button>}
            />
          </>
        ) : null}

        {brands !== null && (brands.length > 0 || selected !== null) ? (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="min-w-0 space-y-6">
              {brands.length > 0 ? (
                <Card>
                  <SectionHeader
                    id="brand-heading"
                    title="Your brand library"
                    description="How your Shorts look. Changing a brand never alters Shorts you already made."
                    actions={
                      <Button variant="secondary" size="sm" onClick={() => pick(null)} disabled={selected === "new"}>
                        <Plus aria-hidden="true" className="size-4" /> New brand
                      </Button>
                    }
                  />
                  <ul aria-label="Brands" className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                    {brands.map((brand) => (
                      <BrandCard
                        key={brand.id}
                        brand={brand}
                        templates={usage ? (usage[brand.id] ?? 0) : null}
                        selected={selected === brand.id}
                        onPick={() => pick(brand)}
                      />
                    ))}
                  </ul>
                </Card>
              ) : (
                <h2 id="brand-heading" className="sr-only">
                  Your brand
                </h2>
              )}
              {selected !== null && spec && layout ? (
                <Card>
            <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-section">{selected === "new" ? "New brand" : "Edit brand"}</h3>
                <p className="mt-1 text-sm text-muted">Colours, logo and the line on your end card.</p>
              </div>
              <div className="flex items-center gap-2">
                {dirty ? <StatusPill tone="warning">Unsaved changes</StatusPill> : null}
                {dirty && selected !== "new" ? (
                  <Button type="button" variant="secondary" size="sm" onClick={() => setDraft(saved)}>
                    <RotateCcw aria-hidden="true" /> Reset
                  </Button>
                ) : null}
              </div>
            </div>
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
                <div className="flex flex-wrap items-center gap-3">
                  <span className="checkerboard flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-block border border-border">
                    {draft.logo ? (
                      // eslint-disable-next-line @next/next/no-img-element -- a private, session-authenticated image
                      <img src={logoUrl(draft.logo)} alt="" className="size-11 object-contain" />
                    ) : (
                      <ImageIcon aria-hidden="true" className="size-5 text-subtle" />
                    )}
                  </span>
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
                </Card>
              ) : null}
            </div>
            {selected !== null && spec && layout ? (
              <aside aria-labelledby="preview-heading" className="xl:sticky xl:top-6 xl:self-start">
                <Card>
                  <h2 id="preview-heading" className="text-section">
                    Live preview
                  </h2>
                  <p className="mt-1 mb-4 text-sm text-muted">How your brand looks on a Short. The rendered Short is the final result.</p>
                  <BrandPreview spec={spec} layout={layout} brand={preview} edit={SAMPLE_EDIT} />
                </Card>
              </aside>
            ) : null}
          </div>
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
