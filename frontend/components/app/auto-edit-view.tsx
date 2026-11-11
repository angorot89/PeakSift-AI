"use client";

import {
  BarChart3,
  BookOpen,
  Captions,
  Check,
  Clapperboard,
  Crop,
  Feather,
  ImageIcon,
  Info,
  Languages,
  Music,
  Palette,
  Pencil,
  Plus,
  RotateCcw,
  Shuffle,
  Sparkles,
  Type,
  Wand2,
  Zap,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { CreateSteps } from "@/components/app/create/create-steps";
import { InlineCheck, OptionCard } from "@/components/app/editor/controls";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";
import { listTemplates, type Template } from "@/lib/brand";
import { summary } from "@/lib/template-rules";
import { selectClasses } from "@/components/ui/select-styles";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { ApiError, errorMessage } from "@/lib/api";
import { listAudio, type AudioAsset } from "@/lib/audio";
import {
  PLAN_STAGES,
  RECIPE_TRAITS,
  applyPlan,
  basedOn,
  createPlan,
  formatSpan,
  getPerformanceContext,
  getPlan,
  isPlanActive,
  listPlans,
  listRecipes,
  missingInputs,
  planSections,
  planEditorLink,
  planSteps,
  plannerNote,
  regeneratePlan,
  retryPlan,
  type AutoEditPlan,
  type PerformanceContext,
  type Recipe,
  type RecipeName,
  type SectionKey,
} from "@/lib/auto-edit";
import type { GeneratedClip } from "@/lib/clips";
import { createHref, editorHref } from "@/lib/edits";
import { formatDuration } from "@/lib/format";
import { loadProjectClip } from "@/lib/project-clip";
import { isProjectId, type Project } from "@/lib/projects";
import { mergeJobs, newer } from "@/lib/status-sync";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

const RECIPE_ICONS: Record<RecipeName, typeof Zap> = {
  clean: Sparkles,
  punchy: Zap,
  story: BookOpen,
  minimal: Feather,
};

const STATUS_TONES: Record<AutoEditPlan["status"], StatusTone> = {
  queued: "processing",
  analyzing: "processing",
  planning: "processing",
  validating: "processing",
  ready: "success",
  applied: "accent",
  failed: "danger",
};
const STATUS_LABELS: Record<AutoEditPlan["status"], string> = {
  queued: "Waiting",
  analyzing: "Preparing",
  planning: "Preparing",
  validating: "Checking",
  ready: "Ready to review",
  applied: "Used",
  failed: "Needs attention",
};

/** A miniature of each recipe's caption look, so the cards read at a glance. */
function RecipeMotif({ recipe }: { recipe: RecipeName }) {
  const caption = {
    clean: <span className="rounded-[3px] bg-black/70 px-1 py-px text-[9px] font-semibold text-white">So clear</span>,
    punchy: (
      <span className="text-[10px] leading-none font-black tracking-tight text-white uppercase [text-shadow:0_1px_0_#000]">
        So <span className="text-amber-300">wild</span>
      </span>
    ),
    story: <span className="text-[9px] font-medium text-white/90 italic">it clicked</span>,
    minimal: <span className="text-[8px] text-white/80">just words</span>,
  }[recipe];
  return (
    <span
      aria-hidden="true"
      className="relative flex aspect-[9/16] w-14 shrink-0 flex-col items-center justify-end overflow-hidden rounded-lg border border-white/10 bg-[linear-gradient(170deg,#3a3f4b,#16181d_70%)] pb-3"
    >
      <span className="absolute top-[24%] left-1/2 size-4 -translate-x-1/2 rounded-full bg-white/20" />
      <span className="absolute top-[40%] left-1/2 h-5 w-8 -translate-x-1/2 rounded-t-full bg-white/10" />
      {recipe === "punchy" ? (
        <span className="absolute top-2 inset-x-1.5 rounded-[3px] bg-accent/90 px-0.5 text-center text-[7px] font-bold text-background">
          HOOK
        </span>
      ) : null}
      {recipe === "story" || recipe === "punchy" ? (
        <span className="absolute top-[22%] right-1 h-4 w-3 rounded-sm border border-white/30 bg-sky-300/30" />
      ) : null}
      <span className="relative px-1 text-center leading-tight">{caption}</span>
    </span>
  );
}

function RecipePicker({
  recipes,
  value,
  onChange,
  name,
}: {
  recipes: Recipe[];
  value: RecipeName;
  onChange: (recipe: RecipeName) => void;
  name: string;
}) {
  return (
    <fieldset className="space-y-3">
      <legend className="text-section">Choose a style</legend>
      <p className="-mt-1 text-sm text-muted">It sets the feel. You can change anything before rendering.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {recipes.map((recipe) => {
          const Icon = RECIPE_ICONS[recipe.name];
          const checked = value === recipe.name;
          return (
            <OptionCard
              key={recipe.name}
              name={name}
              value={recipe.name}
              label={`${recipe.label}: ${recipe.description}`}
              checked={checked}
              onChange={() => onChange(recipe.name)}
              badge={false}
            >
              <span className="flex items-start gap-4 p-4">
                <RecipeMotif recipe={recipe.name} />
                <span className="min-w-0">
                  <span className="flex items-center gap-2 text-title text-foreground">
                    <Icon aria-hidden="true" className={`size-4 ${checked ? "text-accent" : "text-muted"}`} />
                    {recipe.label}
                    <InlineCheck on={checked} />
                  </span>
                  <span className="mt-1 block text-small leading-snug text-pretty text-muted">{recipe.description}</span>
                  <span className="mt-2.5 flex flex-wrap gap-1.5">
                    {RECIPE_TRAITS[recipe.name].map((trait) => (
                      <span key={trait} className="rounded-full bg-surface-3 px-2 py-0.5 text-caption text-muted">
                        {trait}
                      </span>
                    ))}
                  </span>
                </span>
              </span>
            </OptionCard>
          );
        })}
      </div>
    </fieldset>
  );
}

function PlanningState({ plan }: { plan: AutoEditPlan }) {
  const steps = planSteps(plan.status);
  const current = steps.find((s) => s.state === "current");
  return (
    <div className="space-y-5">
      <p className="sr-only" role="status" aria-live="polite">
        {current ? `${current.label}…` : ""}
      </p>
      <ol className="space-y-3" aria-label="Planning progress">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center gap-3 text-sm">
            <span aria-hidden="true" className="flex size-6 shrink-0 items-center justify-center">
              {step.state === "done" ? (
                <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
                  <Check className="size-3" strokeWidth={3} />
                </span>
              ) : step.state === "current" ? (
                <Spinner />
              ) : (
                <span className="size-2 rounded-full bg-white/15" />
              )}
            </span>
            <span className={step.state === "todo" ? "text-subtle" : "text-foreground"}>
              {step.label}
              <span className="sr-only">
                {step.state === "done" ? " (done)" : step.state === "current" ? " (in progress)" : ""}
              </span>
            </span>
          </li>
        ))}
      </ol>
      <p className="text-small text-pretty text-subtle">
        PeakSift is looking at this clip’s framing, word timing and your visuals, and choosing options in the{" "}
        {plan.recipe_label} style. Every choice is checked before you see it. You can leave this page — it keeps going.
      </p>
    </div>
  );
}

const SECTION_ICONS: Record<SectionKey, LucideIcon> = {
  layout: Crop,
  captions: Captions,
  hook: Type,
  visuals: ImageIcon,
  audio: Music,
};

function PlanReview({ plan, editorLink }: { plan: AutoEditPlan; editorLink: string }) {
  const sections = planSections(plan);
  const facts = basedOn(plan.confidence);
  const missing = missingInputs(plan.confidence);
  const notes = plan.explanations?.notes ?? [];
  const note = plannerNote(plan.confidence);
  const template = plan.explanations?.template;
  const market = plan.explanations?.market;
  return (
    <div className="space-y-5">
      {market && market.code !== "global" ? (
        <p className="flex items-start gap-2 text-sm text-muted">
          <Languages aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent-soft" />
          <span>
            Made for {market.name} Mode: your local visuals come first when they match as well as a Global one. Global stays available.
          </span>
        </p>
      ) : null}
      {template ? (
        <p className="flex items-start gap-2 rounded-xl border border-accent/30 bg-accent/[0.05] px-3.5 py-2.5 text-sm text-foreground">
          <Palette aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent-soft" />
          <span>{template.summary}</span>
        </p>
      ) : null}
      {note ? (
        <p className="flex items-start gap-2 text-sm text-muted">
          <Wand2 aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>
            {note}
            {facts.length ? <span className="block text-xs text-subtle">Based on {facts.join(", ")}.</span> : null}
          </span>
        </p>
      ) : null}
      <ul className="space-y-2.5" aria-label="Planned choices">
        {sections.map(({ key, title, section }) => {
          const Icon = SECTION_ICONS[key];
          return (
          <li key={key} className="flex gap-3.5 rounded-xl border border-border bg-surface-2 px-4 py-3.5">
            <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-accent-soft">
              <Icon className="size-[18px]" />
            </span>
            <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-caption font-medium tracking-wide text-subtle uppercase">{title}</h3>
                <p className="mt-0.5 text-sm font-medium break-words text-foreground">{section.choice}</p>
              </div>
              <Link
                href={planEditorLink(editorLink, plan, key)}
                className="-my-1 inline-flex min-h-9 shrink-0 items-center gap-1 rounded-md px-2 text-small text-muted transition-colors hover:bg-surface-3 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:min-h-11"
              >
                <Pencil aria-hidden="true" className="size-3.5" />
                Edit<span className="sr-only"> {title.toLowerCase()}</span>
              </Link>
            </div>
            <p className="mt-0.5 text-small text-pretty text-muted">{section.reason}</p>
            {section.items?.length ? (
              <ul className="mt-2.5 space-y-1.5">
                {section.items.map((item) => (
                  <li key={`${item.start}-${item.asset_name}`} className="flex flex-wrap items-baseline gap-x-2 text-xs">
                    <span className="tabular text-subtle">{formatSpan(item.start, item.end)}</span>
                    <span className="text-foreground">{item.mode === "pip" ? "Picture-in-picture" : "Cutaway"}</span>
                    <span className="min-w-0 break-all text-muted">{item.asset_name}</span>
                    <span className="text-subtle">for “{item.query}”</span>
                  </li>
                ))}
              </ul>
            ) : null}
            </div>
          </li>
          );
        })}
      </ul>
      {plan.performance_hints?.length ? (
        <section aria-labelledby={`patterns-${plan.id}`} className="rounded-xl border border-border px-4 py-3.5">
          <h3 id={`patterns-${plan.id}`} className="flex items-center gap-2 text-sm font-medium text-foreground">
            <BarChart3 aria-hidden="true" className="size-4 text-muted" />
            Patterns from your shorts this plan considered
          </h3>
          <ul className="mt-2 space-y-1 text-small text-pretty text-muted">
            {plan.performance_hints.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-subtle">Weak hints inside the recipe’s choices; associations, not causes.</p>
        </section>
      ) : null}
      {notes.length ? (
        <section aria-labelledby={`notes-${plan.id}`} className="rounded-xl border border-border px-4 py-3.5">
          <h3 id={`notes-${plan.id}`} className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Info aria-hidden="true" className="size-4 text-muted" />
            What Auto Edit left out or changed
          </h3>
          <ul className="mt-2 space-y-1 text-small text-pretty text-muted">
            {notes.map((text) => (
              <li key={text} className="flex gap-2">
                <span aria-hidden="true" className="mt-2 size-1 shrink-0 rounded-full bg-white/30" />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {missing.length ? (
        <div className="space-y-2">
          <p className="text-xs text-pretty text-subtle">
            To give Auto Edit more to work with, open the editor and{" "}
            {missing.map((m) => m.charAt(0).toLowerCase() + m.slice(1)).join("; ")}. Auto Edit never starts these for you.
          </p>
          <ButtonLink href={editorLink} variant="ghost" size="sm">
            Open the editor
          </ButtonLink>
        </div>
      ) : null}
    </div>
  );
}

/** The panel's one-line description follows the plan's state (never "review" while planning). */
function headerNote(composing: boolean, plan: AutoEditPlan | null): string {
  if (composing || !plan) return "PeakSift prepares a first draft; you review it and keep full control.";
  if (plan.status === "failed" || plan.is_stale) return "This draft could not be finished. Try again, or choose another style.";
  if (isPlanActive(plan.status)) return "Preparing a first draft. Every choice is checked before you see it.";
  if (plan.status === "applied")
    return plan.clip_edit_id
      ? "This draft became a version of your Short. Open it in the editor, or try another."
      : "The version made from this draft was deleted. Open its settings in the editor, or try another.";
  return "Here is what PeakSift chose and why. Use it, change anything, or try another.";
}

function PlanHistory({
  plans,
  selectedId,
  onSelect,
}: {
  plans: AutoEditPlan[];
  selectedId: string | null;
  onSelect: (plan: AutoEditPlan) => void;
}) {
  return (
    <ul className="space-y-2" aria-label="Drafts for this clip">
      {plans.map((plan) => {
        const selected = plan.id === selectedId;
        return (
          <li key={plan.id}>
            <button
              type="button"
              onClick={() => onSelect(plan)}
              aria-current={selected ? "true" : undefined}
              className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                selected ? "border-accent/60 bg-accent/[0.06]" : "border-border bg-surface-2 hover:border-border-strong"
              }`}
            >
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">
                  {plan.recipe_label}
                  {plan.generation > 1 ? <span className="text-subtle"> · take {plan.generation}</span> : null}
                </span>
                <span className="tabular block text-xs text-subtle">
                  {new Date(plan.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                </span>
              </span>
              <StatusPill tone={STATUS_TONES[plan.status]}>{STATUS_LABELS[plan.status]}</StatusPill>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function AutoEdit({ project, clip }: { project: Project; clip: GeneratedClip }) {
  const { setUser } = useAuth();
  const router = useRouter();
  // Arriving from "Create a Short" always starts a new draft; otherwise the latest one opens.
  const startNew = useSearchParams().get("new") === "1";
  const id = useId();
  const [recipes, setRecipes] = useState<Recipe[] | null>(null);
  const [music, setMusic] = useState<AudioAsset[]>([]);
  const [plans, setPlans] = useState<AutoEditPlan[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [recipe, setRecipe] = useState<RecipeName>("punchy");
  // V1.7: the template this plan starts from — the one chosen in "Create a Short", else the
  // creator's default; "none" plans with a recipe only.
  const templateParam = useSearchParams().get("template");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState<string>("none");
  const [musicId, setMusicId] = useState<string>("");
  const [patterns, setPatterns] = useState<PerformanceContext | null>(null);
  const [usePatterns, setUsePatterns] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );

  const load = useCallback(
    () =>
      Promise.all([
        listRecipes(),
        listPlans(project.id, clip.video_id, clip.id),
        listAudio(project.id).catch(() => [] as AudioAsset[]),
        getPerformanceContext().catch(() => null), // optional: Auto Edit works without it
        listTemplates().catch(() => [] as Template[]), // optional: Auto Edit works without templates
      ])
        .then(([recipeList, page, audio, context, templateList]) => {
          setRecipes(recipeList);
          setTemplates(templateList);
          const wanted = templateParam === "none" ? null : templateList.find((t) => t.id === templateParam);
          const chosen = templateParam === "none" ? null : (wanted ?? templateList.find((t) => t.is_default) ?? null);
          setTemplateId(chosen?.id ?? "none");
          setPatterns(context);
          setMusic(audio.filter((a) => a.kind === "music"));
          setPlans(page.plans);
          setComposing(startNew || page.plans.length === 0);
          setLoadError(null);
        })
        .catch((err: unknown) => setLoadError(handleError(err))),
    [project.id, clip.video_id, clip.id, handleError, startNew, templateParam],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const plan = useMemo(
    () => (plans ? (plans.find((p) => p.id === selectedId) ?? plans[0] ?? null) : null),
    [plans, selectedId],
  );
  const accept = useCallback(
    (next: AutoEditPlan) =>
      setPlans((current) => {
        const merged = mergeJobs(current, [next], PLAN_STAGES);
        return merged.map((p) => (p.id === next.id ? newer(p, next, PLAN_STAGES) : p));
      }),
    [],
  );

  const running = !!plan && isPlanActive(plan.status) && !plan.is_stale;
  usePolling(
    running && !composing,
    async () => {
      if (!plan) return;
      try {
        accept(await getPlan(project.id, clip.video_id, clip.id, plan.id));
      } catch (err) {
        setError(handleError(err));
      }
    },
    plan?.id ?? null,
  );

  async function act(name: string, work: () => Promise<void>) {
    if (busy) return;
    setBusy(name);
    setError(null);
    try {
      await work();
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(null);
    }
  }

  const start = () =>
    act("create", async () => {
      const template = templates.find((t) => t.id === templateId) ?? null;
      const created = await createPlan(
        project.id,
        clip.video_id,
        clip.id,
        template ? null : recipe, // a template brings its own starting style
        musicId || null,
        usePatterns && !!patterns?.available,
        template?.id ?? null,
      );
      accept(created);
      setSelectedId(created.id);
      setComposing(false);
    });
  const retry = (target: AutoEditPlan) =>
    act("retry", async () => accept(await retryPlan(project.id, clip.video_id, clip.id, target.id)));
  const another = (target: AutoEditPlan) =>
    act("regenerate", async () => {
      const next = await regeneratePlan(project.id, clip.video_id, clip.id, target.id);
      accept(next);
      setSelectedId(next.id);
    });
  const apply = (target: AutoEditPlan) =>
    act("apply", async () => {
      const result = await applyPlan(project.id, clip.video_id, clip.id, target.id);
      accept(result.plan);
      router.push(`${editorHref(project.id, clip.id)}?edit=${result.edit.id}`);
    });

  const editorLink = editorHref(project.id, clip.id);
  const step = composing || !plan ? 1 : plan.status === "ready" ? 2 : plan.status === "applied" ? 3 : 1;
  const header = (
    <PageHeader
      back={{ href: createHref(project.id, clip.id), label: "Start" }}
      title="Create a Short"
      description={
        <span className="inline-flex flex-wrap items-center gap-x-2">
          <span className="text-foreground">{clip.title}</span>
          <span className="tabular text-subtle">· {formatDuration(clip.duration_seconds)}</span>
        </span>
      }
      action={
        <ButtonLink href={editorLink} variant="ghost">
          <Pencil aria-hidden="true" />
          Edit manually instead
        </ButtonLink>
      }
    >
      <div className="mt-5">
        <CreateSteps current={step} />
      </div>
    </PageHeader>
  );

  if (loadError) {
    return (
      <>
        {header}
        <ErrorState title="Auto Edit couldn't be loaded" message={loadError} onRetry={() => void load()} />
      </>
    );
  }
  if (!recipes || !plans) {
    return (
      <>
        {header}
        <div role="status" aria-label="Loading Auto Edit" className="space-y-3">
          <Skeleton className="h-32 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      </>
    );
  }

  let body;
  if (composing || !plan) {
    body = (
      <div className="space-y-6">
        {templates.length ? (
          <div className="space-y-1.5">
            <label htmlFor={`${id}-template`} className="block text-sm font-medium text-foreground">
              Template
            </label>
            <select
              id={`${id}-template`}
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              className={`${selectClasses} w-full sm:max-w-sm`}
              aria-describedby={`${id}-template-hint`}
            >
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.is_default ? " (default)" : ""}
                </option>
              ))}
              <option value="none">No template — choose a recipe</option>
            </select>
            <p id={`${id}-template-hint`} className="text-xs text-subtle">
              {templateId !== "none"
                ? `${summary(templates.find((t) => t.id === templateId)!.config, Boolean(templates.find((t) => t.id === templateId)!.brand?.has_logo))}. You can change anything before rendering.`
                : "Auto Edit plans with the recipe you choose below."}
            </p>
          </div>
        ) : null}
        {templateId === "none" ? <RecipePicker recipes={recipes} value={recipe} onChange={setRecipe} name={`${id}-recipe`} /> : null}
        <div className="space-y-1.5">
          <label htmlFor={`${id}-music`} className="block text-sm font-medium text-foreground">
            Background music
          </label>
          <select
            id={`${id}-music`}
            value={musicId}
            onChange={(e) => setMusicId(e.target.value)}
            className={`${selectClasses} w-full sm:max-w-sm`}
            aria-describedby={`${id}-music-hint`}
          >
            <option value="">No music</option>
            {music.map((track) => (
              <option key={track.id} value={track.id}>
                {track.display_name}
              </option>
            ))}
          </select>
          <p id={`${id}-music-hint`} className="text-xs text-subtle">
            Auto Edit never picks music for you. Choose one of your tracks to have it mixed under your voice.
          </p>
        </div>
        {patterns?.available ? (
          <div className="space-y-2 rounded-xl border border-border px-4 py-3.5">
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={usePatterns}
                onChange={(e) => setUsePatterns(e.target.checked)}
                className="mt-1 size-4 accent-[var(--accent)]"
              />
              <span>
                <span className="font-medium text-foreground">Consider patterns from my published shorts</span>
                <span className="block text-xs text-subtle">
                  Weak hints from {patterns.sample_size} of your shorts{patterns.simulated ? " (simulated data)" : ""}.
                  The recipe and this clip come first; nothing here predicts results.
                </span>
              </span>
            </label>
            {usePatterns ? (
              <ul className="space-y-1 pl-7 text-xs text-muted">
                {patterns.hints.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button size="lg" onClick={() => void start()} disabled={busy !== null}>
            <Wand2 aria-hidden="true" />
            {busy === "create" ? "Starting…" : "Prepare my edit"}
          </Button>
          {plans.length ? (
            <Button size="lg" variant="ghost" onClick={() => setComposing(false)}>
              See earlier drafts
            </Button>
          ) : null}
        </div>
      </div>
    );
  } else if (isPlanActive(plan.status) && !plan.is_stale) {
    body = <PlanningState plan={plan} />;
  } else if (plan.status === "failed" || plan.is_stale) {
    body = (
      <InlineAlert
        title={plan.status === "failed" ? "This draft couldn't be prepared" : "Preparing stopped responding"}
        action={
          <Button size="sm" onClick={() => void retry(plan)} disabled={busy !== null}>
            <RotateCcw aria-hidden="true" />
            {busy === "retry" ? "Trying again…" : "Try again"}
          </Button>
        }
      >
        {plan.error_message ?? "The work stopped reporting progress. Nothing else was changed."}
      </InlineAlert>
    );
  } else {
    body = <PlanReview plan={plan} editorLink={editorLink} />;
  }

  const reviewing = !composing && plan && (plan.status === "ready" || plan.status === "applied");
  return (
    <>
      {header}
      <div className="max-w-3xl space-y-6">
        <section aria-labelledby={`${id}-main`} className="min-w-0 rounded-2xl border border-border bg-surface">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-4 sm:px-6">
            <div className="min-w-0">
              <h2 id={`${id}-main`} className="text-title text-foreground">
                {composing || !plan ? "Auto Edit" : `${plan.recipe_label} draft`}
              </h2>
              <p className="mt-0.5 text-sm text-muted">{headerNote(composing, plan)}</p>
            </div>
            {!composing && plan ? (
              <StatusPill tone={STATUS_TONES[plan.status]}>{STATUS_LABELS[plan.status]}</StatusPill>
            ) : null}
          </header>
          <div className="px-4 py-5 sm:px-6">{body}</div>
          {reviewing && plan ? (
            <div className="flex flex-col gap-2 border-t border-border px-4 py-4 sm:flex-row sm:flex-wrap sm:items-center sm:px-6">
              {plan.status === "applied" && plan.clip_edit_id ? (
                <ButtonLink href={planEditorLink(editorLink, plan)} size="lg">
                  <Clapperboard aria-hidden="true" />
                  Open in editor
                </ButtonLink>
              ) : plan.status === "applied" ? null : (
                <Button size="lg" onClick={() => void apply(plan)} disabled={busy !== null}>
                  <Check aria-hidden="true" />
                  {busy === "apply" ? "Starting the render…" : "Use this edit"}
                </Button>
              )}
              {plan.status === "ready" || !plan.clip_edit_id ? (
                <ButtonLink href={`${editorLink}?plan=${plan.id}`} variant="secondary" size="lg">
                  <Pencil aria-hidden="true" />
                  Continue to editor
                </ButtonLink>
              ) : null}
              <Button size="lg" variant="ghost" onClick={() => void another(plan)} disabled={busy !== null} className="sm:ml-auto">
                <Shuffle aria-hidden="true" />
                {busy === "regenerate" ? "Starting…" : "Try another"}
              </Button>
            </div>
          ) : null}
          {reviewing && plan?.status === "ready" ? (
            <p className="px-4 pb-4 text-small text-subtle sm:px-6">
              “Use this edit” renders your Short with these choices. “Continue to editor” lets you change them first.
            </p>
          ) : null}
          {error ? (
            <div className="px-4 pb-4 sm:px-6">
              <InlineAlert title="That didn't work">{error}</InlineAlert>
            </div>
          ) : null}
        </section>
        {plans.length ? (
          <details className="group rounded-2xl border border-border bg-surface">
            <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-4 py-3 text-sm text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent sm:px-6 [&::-webkit-details-marker]:hidden">
              <span>
                All drafts for this clip <span className="tabular text-subtle">· {plans.length}</span>
              </span>
              <span aria-hidden="true" className="text-subtle transition-transform group-open:rotate-180">
                ▾
              </span>
            </summary>
            <div className="space-y-3 border-t border-border px-4 py-4 sm:px-6">
              <PlanHistory
                plans={plans}
                selectedId={composing ? null : (plan?.id ?? null)}
                onSelect={(p) => {
                  setSelectedId(p.id);
                  setComposing(false);
                }}
              />
              {!composing ? (
                <Button size="sm" variant="ghost" onClick={() => setComposing(true)}>
                  <Plus aria-hidden="true" />
                  New draft in another style
                </Button>
              ) : null}
            </div>
          </details>
        ) : null}
      </div>
    </>
  );
}

/**
 * /projects/[id]/clips/[clipId]/auto-edit — the Style and Review steps of creating a Short:
 * choose a recipe, watch the draft being prepared, review each choice, then use or adjust it.
 */
export function AutoEditView() {
  const { id, clipId } = useParams<{ id: string; clipId: string }>();
  const load = useCallback(() => loadProjectClip(id, clipId), [id, clipId]);
  const { data, error, loading, reload } = useApi(load);

  if (loading) {
    return (
      <div role="status" aria-label="Loading Auto Edit">
        <Skeleton className="mb-3 h-4 w-32" />
        <Skeleton className="mb-8 h-8 w-56" />
        <Skeleton className="h-96 rounded-2xl" />
      </div>
    );
  }
  if (error || !data) {
    const notFound = error === "Clip not found" || error === "Project not found";
    return (
      <>
        <PageHeader back={{ href: isProjectId(id) ? `/projects/${id}/clips` : "/projects", label: "Moments" }} title="Create a Short" />
        {notFound ? (
          <EmptyState
            icon={Clapperboard}
            title="Clip not found"
            description="This clip does not exist or you do not have access to it."
            action={<ButtonLink href="/projects" variant="secondary">Back to projects</ButtonLink>}
          />
        ) : (
          <ErrorState title="This clip couldn't be loaded" message={error ?? "Try again."} onRetry={reload} />
        )}
      </>
    );
  }
  if (data.clip.status !== "ready") {
    return (
      <>
        <PageHeader back={{ href: `/projects/${id}/clips`, label: "Moments" }} title="Create a Short" />
        <EmptyState
          icon={Clapperboard}
          title="This clip isn't ready yet"
          description="Auto Edit starts once the clip has been prepared."
          action={<ButtonLink href={createHref(id, clipId)} variant="secondary">See its progress</ButtonLink>}
        />
      </>
    );
  }
  return <AutoEdit project={data.project} clip={data.clip} />;
}
