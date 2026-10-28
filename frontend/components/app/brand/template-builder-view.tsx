"use client";

import { Captions, Clapperboard, Images, Music2, Palette, Sparkles, Star, Type } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/app/page-header";
import { BrandPreview } from "@/components/app/brand/brand-preview";
import { PresetSample } from "@/components/app/editor/caption-layer";
import { ControlGroup, InlineCheck, OptionCard } from "@/components/app/editor/controls";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/inline-alert";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ToolTabs, type TabItem } from "@/components/ui/tool-tabs";
import { errorMessage } from "@/lib/api";
import {
  createTemplate,
  getBrandLayout,
  getTemplate,
  listBrands,
  listTemplateStarters,
  logoUrl,
  updateTemplate,
  type Brand,
  type BrandLayout,
  type Template,
  type TemplateRecipe,
  type TemplateSettings,
  type TemplateStarter,
} from "@/lib/brand";
import { getCaptionStyles, type CaptionStyles } from "@/lib/captions";
import { BLANK, freeHookPositions, RECIPE_LABELS, resolved, sameSettings, startFrom } from "@/lib/template-rules";

type Tool = "style" | "captions" | "opening" | "visuals" | "sound" | "brand";

type Meta = { name: string; description: string; recipe: TemplateRecipe | null; brandId: string | null; isDefault: boolean };

const FRAMING: { value: TemplateSettings["framing"]; label: string; hint: string }[] = [
  { value: "auto", label: "Auto", hint: "Auto Edit picks the framing" },
  { value: "smart_reframe", label: "Smart Reframe", hint: "Follows faces when the clip allows it" },
  { value: "blur_background", label: "Blur background", hint: "The whole frame over a soft fill" },
  { value: "center_crop", label: "Center crop", hint: "Fills the frame from the centre" },
  { value: "fit", label: "Fit", hint: "The whole frame on dark" },
];

function Switch({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-surface-2 px-3.5 py-3">
      <div className="min-w-0">
        <p id={`${id}-label`} className="text-sm font-medium text-foreground">
          {label}
        </p>
        {hint ? (
          <p id={`${id}-hint`} className="text-xs text-subtle">
            {hint}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:h-7 ${
          checked ? "border-accent bg-accent" : "border-border-strong bg-surface-3"
        }`}
      >
        <span className="sr-only">{checked ? "On" : "Off"}</span>
        <span aria-hidden="true" className={`inline-block size-[18px] rounded-full bg-white shadow transition-transform duration-150 motion-reduce:transition-none ${checked ? "translate-x-[22px]" : "translate-x-[2px]"}`} />
      </button>
    </div>
  );
}

function Advanced({ children }: { children: ReactNode }) {
  return (
    <details className="group rounded-xl border border-border bg-surface/60">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-3.5 text-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
        Advanced
        <span aria-hidden="true" className="text-subtle transition-transform group-open:rotate-90 motion-reduce:transition-none">
          ›
        </span>
      </summary>
      <div className="space-y-5 border-t border-border p-3.5">{children}</div>
    </details>
  );
}

function Choice<T extends string>({ legend, hint, value, options, onChange }: { legend: string; hint?: string; value: T; options: { value: T; label: string; disabled?: boolean }[]; onChange: (v: T) => void }) {
  return (
    <ControlGroup legend={legend} hint={hint}>
      <SegmentedControl label={legend} options={options} value={value} onChange={onChange} />
    </ControlGroup>
  );
}

const STYLE = "style";

export function TemplateBuilderView({ templateId, start }: { templateId?: string; start?: string | null }) {
  const router = useRouter();
  const toast = useToast();
  const [spec, setSpec] = useState<CaptionStyles | null>(null);
  const [layout, setLayout] = useState<BrandLayout | null>(null);
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [starters, setStarters] = useState<TemplateStarter[] | null>(null);
  const [existing, setExisting] = useState<Template | null>(null);
  const [settings, setSettings] = useState<TemplateSettings>(BLANK);
  const [savedSettings, setSavedSettings] = useState<TemplateSettings>(BLANK);
  const [meta, setMeta] = useState<Meta>({ name: "", description: "", recipe: null, brandId: null, isDefault: false });
  const [savedMeta, setSavedMeta] = useState<Meta | null>(null);
  const [tool, setTool] = useState<Tool>(STYLE);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [picked, setPicked] = useState(Boolean(templateId) || Boolean(start));

  useEffect(() => {
    let cancelled = false;
    Promise.all([getCaptionStyles(), getBrandLayout(), listBrands(), listTemplateStarters(), templateId ? getTemplate(templateId) : Promise.resolve(null)])
      .then(([styles, numbers, brandList, starterList, template]) => {
        if (cancelled) return;
        setSpec(styles);
        setLayout(numbers);
        setBrands(brandList);
        setStarters(starterList);
        const defaultBrand = brandList.find((b) => b.is_default)?.id ?? null;
        if (template) {
          setExisting(template);
          const loaded = { ...BLANK, ...template.config };
          const m = { name: template.name, description: template.description, recipe: template.recipe, brandId: template.brand?.id ?? null, isDefault: template.is_default };
          setSettings(loaded);
          setSavedSettings(loaded);
          setMeta(m);
          setSavedMeta(m);
        } else {
          const starter = starterList.find((s) => s.recipe === start) ?? null;
          setSettings(startFrom(starter));
          setMeta((m) => ({ ...m, recipe: starter?.recipe ?? null, brandId: defaultBrand }));
        }
      })
      .catch((failure: unknown) => !cancelled && setLoadError(errorMessage(failure)));
    return () => {
      cancelled = true;
    };
  }, [templateId, start]);

  const starter = starters?.find((s) => s.recipe === meta.recipe)?.config ?? null;
  const view = resolved(settings, starter);
  const brand = brands?.find((b) => b.id === meta.brandId) ?? null;
  const dirty = savedMeta === null || !sameSettings(settings, savedSettings) || JSON.stringify(meta) !== JSON.stringify(savedMeta);

  useEffect(() => {
    if (!dirty || !picked) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, picked]);

  const previewBrand = useMemo(
    () => ({
      name: brand?.name ?? "Your brand",
      primary: brand?.primary_color ?? "#3F3F46",
      accent: brand?.accent_color ?? null,
      emphasis: brand?.caption_emphasis_color ?? null,
      logoUrl: brand?.logo ? logoUrl(brand.logo) : null,
      corner: brand?.logo_position ?? "top_right",
      size: brand?.logo_size ?? "small",
      endText: brand?.end_card_text ?? null,
    }),
    [brand],
  );

  const set = (changes: Partial<TemplateSettings>) => setSettings((s) => ({ ...s, ...changes }));

  async function save() {
    if (!meta.name.trim()) {
      setNameError("Give the template a name.");
      document.getElementById("template-name")?.focus();
      return;
    }
    setNameError(null);
    setSaving(true);
    setError(null);
    const input = {
      name: meta.name.trim(),
      description: meta.description.trim(),
      recipe: meta.recipe,
      brand_profile_id: meta.brandId,
      config: settings,
      is_default: meta.isDefault,
    };
    try {
      const result = existing ? await updateTemplate(existing.id, input) : await createTemplate(input);
      const loaded = { ...BLANK, ...result.config };
      const m = { name: result.name, description: result.description, recipe: result.recipe, brandId: result.brand?.id ?? null, isDefault: result.is_default };
      setExisting(result);
      setSettings(loaded);
      setSavedSettings(loaded);
      setMeta(m);
      setSavedMeta(m);
      toast("Template saved");
      if (!templateId) router.replace(`/brand/templates/${result.id}`);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSaving(false);
    }
  }

  if (loadError) return <InlineAlert title="The template couldn't load">{loadError}</InlineAlert>;
  if (!spec || !layout || !starters || !brands) return <Skeleton className="h-[40rem] rounded-2xl" />;

  if (!picked) {
    return (
      <div>
        <PageHeader title="New template" description="Start from a style you like, then make it yours." back={{ href: "/brand", label: "Brand Studio" }} />
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Starting points">
          {[...starters.map((s) => ({ key: s.recipe as string, label: s.label, text: s.description })), { key: "blank", label: "Blank", text: "Every setting left to the style you pick later." }].map((item) => (
            <li key={item.key}>
              <button
                type="button"
                onClick={() => {
                  const chosen = starters.find((s) => s.recipe === item.key) ?? null;
                  setSettings(startFrom(chosen));
                  setMeta((m) => ({ ...m, recipe: chosen?.recipe ?? null }));
                  setPicked(true);
                }}
                className="flex h-full min-h-24 w-full flex-col items-start gap-1 rounded-2xl border border-border bg-surface p-4 text-left transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <span className="text-title text-foreground">{item.label}</span>
                <span className="text-sm text-muted">{item.text}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const tabs: TabItem<Tool>[] = [
    { key: "style", label: "Style", icon: Clapperboard },
    { key: "captions", label: "Captions", icon: Captions, mark: settings.captions ? "on" : null },
    { key: "opening", label: "Opening", icon: Type, mark: settings.hook ? "on" : null },
    { key: "visuals", label: "Visuals", icon: Images, mark: settings.broll !== "none" ? "on" : null },
    { key: "sound", label: "Sound", icon: Music2 },
    { key: "brand", label: "Brand", icon: Palette, mark: brand ? "on" : null },
  ];

  return (
    <div>
      <PageHeader
        title={existing ? existing.name : "New template"}
        description="How your Shorts are edited. Changes apply to Shorts you make from now on — never to ones you already made."
        back={{ href: "/brand", label: "Brand Studio" }}
      />
      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-6 lg:self-start">
          <BrandPreview spec={spec} layout={layout} brand={previewBrand} edit={{ ...view, preset: view.preset, captionPosition: view.captionPosition, hookStyle: view.hookStyle, hookPosition: view.hookPosition }} />
        </div>
        <Card className="min-w-0 space-y-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="template-name" label="Template name" value={meta.name} maxLength={60} placeholder="e.g. Punchy Gaming" error={nameError} onChange={(e) => setMeta({ ...meta, name: e.target.value })} />
            <Field id="template-description" label="Description (optional)" value={meta.description} maxLength={200} placeholder="When you use it" onChange={(e) => setMeta({ ...meta, description: e.target.value })} />
          </div>
          <ToolTabs items={tabs} value={tool} onChange={setTool} label="Template settings" idBase="template" />
          <div role="tabpanel" id={`template-panel-${tool}`} aria-labelledby={`template-tab-${tool}`} className="space-y-5">
            {tool === "style" ? (
              <>
                <Choice
                  legend="Starting style"
                  hint="Fills in whatever you leave to the style"
                  value={meta.recipe ?? "none"}
                  options={[...(Object.keys(RECIPE_LABELS) as TemplateRecipe[]).map((r) => ({ value: r as string, label: RECIPE_LABELS[r] })), { value: "none", label: "None" }]}
                  onChange={(r) => setMeta({ ...meta, recipe: r === "none" ? null : (r as TemplateRecipe) })}
                />
                <ControlGroup legend="Framing">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {FRAMING.map((f) => (
                      <OptionCard key={f.value} name="template-framing" value={f.value} label={`${f.label}: ${f.hint}`} checked={settings.framing === f.value} onChange={() => set({ framing: f.value })} badge={false} className="px-3 py-2.5">
                        <span className="flex items-center justify-between gap-1.5 text-small font-medium text-foreground">
                          {f.label}
                          <InlineCheck on={settings.framing === f.value} />
                        </span>
                        <span className="block text-caption leading-snug text-subtle">{f.hint}</span>
                      </OptionCard>
                    ))}
                  </div>
                </ControlGroup>
                {settings.framing === "smart_reframe" ? (
                  <p className="text-caption text-subtle">When a clip&apos;s faces can&apos;t be followed confidently, Auto Edit keeps its own framing and says so.</p>
                ) : null}
              </>
            ) : null}

            {tool === "captions" ? (
              <>
                <Switch label="Captions" hint="Burned in, with the spoken word emphasised" checked={settings.captions} onChange={(captions) => set({ captions })} />
                {settings.captions ? (
                  <>
                    <ControlGroup legend="Caption style" hint={settings.caption_preset ? undefined : "Using the style's choice"}>
                      <div className="grid grid-cols-2 gap-2">
                        {spec.presets.map((preset) => (
                          <OptionCard key={preset.name} name="template-preset" value={preset.name} label={preset.label} checked={view.preset === preset.name} onChange={() => set({ caption_preset: preset.name })} badge={false} className="overflow-hidden">
                            <span aria-hidden="true" className="flex h-[60px] items-center justify-center bg-[linear-gradient(135deg,#3f3f46,#1f1f23)] px-2">
                              <PresetSample spec={spec} preset={preset.name} />
                            </span>
                            <span className="flex items-center justify-between gap-1.5 px-2.5 py-2 text-small font-medium text-foreground">
                              {preset.label}
                              <InlineCheck on={view.preset === preset.name} />
                            </span>
                          </OptionCard>
                        ))}
                      </div>
                    </ControlGroup>
                    <Choice
                      legend="Caption position"
                      value={view.captionPosition}
                      options={[{ value: "top" as const, label: "Top" }, { value: "center" as const, label: "Center" }, { value: "bottom" as const, label: "Bottom" }]}
                      onChange={(caption_position) => {
                        const hookPosition = settings.hook_position === caption_position ? freeHookPositions(caption_position)[0] : settings.hook_position;
                        set({ caption_position, hook_position: hookPosition });
                      }}
                    />
                  </>
                ) : null}
              </>
            ) : null}

            {tool === "opening" ? (
              <>
                <Switch label="Opening hook" hint="A short line from the clip over the first seconds" checked={settings.hook} onChange={(hook) => set({ hook })} />
                {settings.hook ? (
                  <>
                    <Choice
                      legend="Hook style"
                      value={view.hookStyle}
                      options={spec.hook.styles.map((s) => ({ value: s.name, label: s.label }))}
                      onChange={(hook_style) => set({ hook_style })}
                    />
                    <Choice
                      legend="Hook position"
                      hint={settings.captions ? "Never where the captions are" : undefined}
                      value={view.hookPosition}
                      options={(["top", "center"] as const).map((p) => ({ value: p, label: p === "top" ? "Top" : "Center", disabled: settings.captions && view.captionPosition === p }))}
                      onChange={(hook_position) => set({ hook_position })}
                    />
                    <Advanced>
                      <ControlGroup legend="Seconds on screen" hint={`${view.hookSeconds.toFixed(1)} s`}>
                        <input
                          type="range"
                          min={spec.hook.min_seconds}
                          max={spec.hook.max_seconds}
                          step={0.5}
                          value={view.hookSeconds}
                          aria-label="Hook seconds on screen"
                          onChange={(e) => set({ hook_seconds: Number(e.target.value) })}
                          className="w-full accent-[var(--color-accent)]"
                        />
                      </ControlGroup>
                    </Advanced>
                    <p className="text-caption text-subtle">The words always come from the clip itself.</p>
                  </>
                ) : null}
              </>
            ) : null}

            {tool === "visuals" ? (
              <Choice
                legend="B-roll"
                hint="Picked from each project's own visuals"
                value={settings.broll}
                options={[{ value: "none" as const, label: "None" }, { value: "light" as const, label: "Light (one)" }, { value: "recipe" as const, label: "As the style suggests" }]}
                onChange={(broll) => set({ broll })}
              />
            ) : null}

            {tool === "sound" ? (
              <>
                <p className="rounded-xl border border-border bg-surface-2 px-3.5 py-3 text-sm text-muted">
                  Templates never add music. When you pick music for a Short, it plays at this level.
                </p>
                <Choice
                  legend="Music level"
                  value={settings.music_level ?? "style"}
                  options={[{ value: "style", label: "Style's" }, { value: "quiet", label: "Quiet" }, { value: "low", label: "Low" }, { value: "medium", label: "Medium" }]}
                  onChange={(level) => set({ music_level: level === "style" ? null : (level as TemplateSettings["music_level"]) })}
                />
                <Switch label="Sound effects" hint="Transition sounds where the style uses them and you have a matching effect" checked={settings.sound_effects} onChange={(sound_effects) => set({ sound_effects })} />
                <Advanced>
                  <Choice
                    legend="Music under speech (ducking)"
                    value={settings.ducking ?? "style"}
                    options={[{ value: "style", label: "Style's" }, { value: "off", label: "Off" }, { value: "light", label: "Light" }, { value: "medium", label: "Medium" }, { value: "strong", label: "Strong" }]}
                    onChange={(d) => set({ ducking: d === "style" ? null : (d as TemplateSettings["ducking"]) })}
                  />
                  <Switch label="Even loudness" hint="Normalize the final mix" checked={settings.normalize_loudness} onChange={(normalize_loudness) => set({ normalize_loudness })} />
                </Advanced>
              </>
            ) : null}

            {tool === "brand" ? (
              <>
                <Choice
                  legend="Brand"
                  value={meta.brandId ?? "none"}
                  options={[...brands.map((b) => ({ value: b.id, label: b.name })), { value: "none", label: "No brand" }]}
                  onChange={(id) => setMeta({ ...meta, brandId: id === "none" ? null : id })}
                />
                {brands.length === 0 ? (
                  <p className="text-sm text-muted">
                    No brand yet —{" "}
                    <Link href="/brand" className="text-foreground underline underline-offset-2">
                      create one in Brand Studio
                    </Link>
                    .
                  </p>
                ) : null}
                {brand ? (
                  <>
                    <Switch label="Show the logo" hint={brand.logo ? "In its corner, clear of captions and the hook" : "This brand has no logo yet"} checked={settings.logo} onChange={(logo) => set({ logo })} />
                    <Switch label="End card" hint="Appended after the clip: the Short gets longer" checked={settings.end_card} onChange={(end_card) => set({ end_card, end_card_seconds: end_card ? (settings.end_card_seconds ?? 2) : null })} />
                    {settings.end_card ? (
                      <ControlGroup legend="End card length" hint={`+${view.endCardSeconds.toFixed(1)} s to every Short`}>
                        <input
                          type="range"
                          min={layout.end_card_seconds[0]}
                          max={layout.end_card_seconds[1]}
                          step={0.5}
                          value={view.endCardSeconds}
                          aria-label="End card seconds"
                          onChange={(e) => set({ end_card_seconds: Number(e.target.value) })}
                          className="w-full accent-[var(--color-accent)]"
                        />
                      </ControlGroup>
                    ) : null}
                  </>
                ) : null}
              </>
            ) : null}
          </div>

          <label className="flex min-h-11 items-center gap-3 text-sm text-foreground">
            <input type="checkbox" checked={meta.isDefault} onChange={(e) => setMeta({ ...meta, isDefault: e.target.checked })} className="size-5 accent-[var(--color-accent)]" />
            <span className="inline-flex items-center gap-1.5">
              <Star aria-hidden="true" className="size-4 text-accent-soft" /> Start new Shorts from this template
            </span>
          </label>
          {error ? <InlineAlert title="That didn't work">{error}</InlineAlert> : null}
          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
            <Button onClick={() => void save()} disabled={saving || (!dirty && Boolean(existing))}>
              <Sparkles aria-hidden="true" className="size-4" />
              {saving ? "Saving…" : existing ? "Save template" : "Create template"}
            </Button>
            <p className="text-caption text-subtle" role="status">
              {dirty ? "Unsaved changes" : "Saved"}
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
