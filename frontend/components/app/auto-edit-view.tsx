"use client";

import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  CircleAlert,
  Clapperboard,
  Feather,
  Info,
  ListChecks,
  Pencil,
  Plus,
  RotateCcw,
  Shuffle,
  Sparkles,
  Wand2,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { ControlGroup, InlineCheck, OptionCard } from "@/components/app/editor/controls";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";
import { selectClasses } from "@/components/ui/select-styles";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { ApiError, errorMessage } from "@/lib/api";
import { listAudio, type AudioAsset } from "@/lib/audio";
import {
  PLAN_STAGES,
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
  planSteps,
  plannerNote,
  regeneratePlan,
  retryPlan,
  type AutoEditPlan,
  type PerformanceContext,
  type Recipe,
  type RecipeName,
} from "@/lib/auto-edit";
import type { GeneratedClip } from "@/lib/clips";
import { editorHref } from "@/lib/edits";
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
  analyzing: "Analyzing",
  planning: "Planning",
  validating: "Checking",
  ready: "Ready",
  applied: "Used",
  failed: "Failed",
};

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
    <ControlGroup legend="Recipe" hint="Sets the style; you can change anything later">
      <div className="grid gap-2.5 sm:grid-cols-2">
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
              <span className="flex items-start gap-3 p-3.5">
                <span
                  aria-hidden="true"
                  className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${
                    checked ? "bg-accent/15 text-accent" : "bg-surface-3 text-muted"
                  }`}
                >
                  <Icon className="size-[18px]" />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                    {recipe.label}
                    <InlineCheck on={checked} />
                  </span>
                  <span className="mt-0.5 block text-xs leading-snug text-pretty text-muted">{recipe.description}</span>
                </span>
              </span>
            </OptionCard>
          );
        })}
      </div>
    </ControlGroup>
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
      <p className="text-xs text-pretty text-subtle">
        Auto Edit reads what PeakSift already knows about this clip — framing, word timing, B-roll suggestions and your
        assets — and chooses options for the {plan.recipe_label} recipe. Every choice is checked before you see it. You
        can leave this page; the plan keeps going.
      </p>
    </div>
  );
}

function PlanReview({ plan, editorLink }: { plan: AutoEditPlan; editorLink: string }) {
  const sections = planSections(plan);
  const facts = basedOn(plan.confidence);
  const missing = missingInputs(plan.confidence);
  const notes = plan.explanations?.notes ?? [];
  const note = plannerNote(plan.confidence);
  return (
    <div className="space-y-5">
      {note ? (
        <p className="flex items-start gap-2 text-sm text-muted">
          <Wand2 aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>
            {note}
            {facts.length ? <span className="block text-xs text-subtle">Based on {facts.join(", ")}.</span> : null}
          </span>
        </p>
      ) : null}
      <ul className="grid gap-2.5 sm:grid-cols-2" aria-label="Planned choices">
        {sections.map(({ key, title, section }) => (
          <li
            key={key}
            className={`rounded-xl border border-border bg-surface-2 px-4 py-3.5 ${
              key === "layout" || key === "captions" ? "" : "sm:col-span-2"
            }`}
          >
            <p className="text-caption font-medium tracking-wide text-subtle uppercase">{title}</p>
            <p className="mt-1 text-sm font-medium break-words text-foreground">{section.choice}</p>
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
          </li>
        ))}
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
        <p className="text-xs text-pretty text-subtle">
          To give Auto Edit more to work with, open the{" "}
          <Link href={editorLink} className="text-accent-soft underline-offset-2 hover:underline">
            editor
          </Link>{" "}
          and {missing.map((m) => m.charAt(0).toLowerCase() + m.slice(1)).join("; ")}. Auto Edit never starts these for
          you.
        </p>
      ) : null}
    </div>
  );
}

/** The panel's one-line description follows the plan's state (never "review" while planning). */
function headerNote(composing: boolean, plan: AutoEditPlan | null): string {
  if (composing || !plan) return "PeakSift proposes a first draft; you review it and keep full control.";
  if (plan.status === "failed" || plan.is_stale) return "This plan could not be finished. Retry it, or start a new plan.";
  if (isPlanActive(plan.status)) return "PeakSift is preparing a first draft. Every choice is checked before you see it.";
  if (plan.status === "applied")
    return plan.clip_edit_id
      ? "This plan is in use as a version. Open it in the editor, or try another plan."
      : "This plan's version was deleted. Open its settings in the editor, or try another plan.";
  return "Review the choices, then use them, adjust them in the editor, or try another plan.";
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
    <ul className="space-y-2" aria-label="Plans for this clip">
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
                  {plan.generation > 1 ? <span className="text-subtle"> · try {plan.generation}</span> : null}
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
  const id = useId();
  const [recipes, setRecipes] = useState<Recipe[] | null>(null);
  const [music, setMusic] = useState<AudioAsset[]>([]);
  const [plans, setPlans] = useState<AutoEditPlan[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [recipe, setRecipe] = useState<RecipeName>("punchy");
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
      ])
        .then(([recipeList, page, audio, context]) => {
          setRecipes(recipeList);
          setPatterns(context);
          setMusic(audio.filter((a) => a.kind === "music"));
          setPlans(page.plans);
          setComposing(page.plans.length === 0);
          setLoadError(null);
        })
        .catch((err: unknown) => setLoadError(handleError(err))),
    [project.id, clip.video_id, clip.id, handleError],
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
      const created = await createPlan(
        project.id,
        clip.video_id,
        clip.id,
        recipe,
        musicId || null,
        usePatterns && !!patterns?.available,
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
  const header = (
    <PageHeader
      back={{ href: editorLink, label: "Short-form editor" }}
      title="Auto Edit"
      description={
        <span className="inline-flex flex-wrap items-center gap-x-2">
          <span className="text-foreground">{clip.title}</span>
          <span className="tabular text-subtle">· {formatDuration(clip.duration_seconds)} clip</span>
        </span>
      }
      action={
        <ButtonLink href={editorLink} variant="secondary">
          <Pencil aria-hidden="true" />
          Edit manually
        </ButtonLink>
      }
    />
  );

  if (loadError) {
    return (
      <>
        {header}
        <ErrorState title="Auto Edit could not be loaded" message={loadError} onRetry={() => void load()} />
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
        <RecipePicker recipes={recipes} value={recipe} onChange={setRecipe} name={`${id}-recipe`} />
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
            {busy === "create" ? "Starting…" : "Create edit plan"}
          </Button>
          {plans.length ? (
            <Button size="lg" variant="ghost" onClick={() => setComposing(false)}>
              Back to plans
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
        title={plan.status === "failed" ? "The plan could not be made" : "Planning stopped responding"}
        action={
          <Button size="sm" onClick={() => void retry(plan)} disabled={busy !== null}>
            <RotateCcw aria-hidden="true" />
            {busy === "retry" ? "Retrying…" : "Retry"}
          </Button>
        }
      >
        {plan.error_message ?? "The worker stopped reporting progress."}
      </InlineAlert>
    );
  } else {
    body = <PlanReview plan={plan} editorLink={editorLink} />;
  }

  const reviewing = !composing && plan && (plan.status === "ready" || plan.status === "applied");
  return (
    <>
      {header}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-8">
        <section aria-labelledby={`${id}-main`} className="min-w-0 rounded-2xl border border-border bg-surface">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-4 sm:px-6">
            <div className="min-w-0">
              <h2 id={`${id}-main`} className="text-title text-foreground">
                {composing || !plan ? "Plan an edit" : `${plan.recipe_label} plan`}
              </h2>
              <p className="mt-0.5 text-sm text-muted">{headerNote(composing, plan)}</p>
            </div>
            {!composing && plan ? (
              <StatusPill tone={STATUS_TONES[plan.status]}>{STATUS_LABELS[plan.status]}</StatusPill>
            ) : null}
          </header>
          <div className="px-4 py-5 sm:px-6">{body}</div>
          {reviewing && plan ? (
            <div className="flex flex-col gap-2 border-t border-border px-4 py-4 sm:flex-row sm:flex-wrap sm:px-6">
              {plan.status === "applied" && plan.clip_edit_id ? (
                <ButtonLink href={`${editorLink}?edit=${plan.clip_edit_id}`} size="lg">
                  <Clapperboard aria-hidden="true" />
                  Open in editor
                </ButtonLink>
              ) : plan.status === "applied" ? null : (
                <Button size="lg" onClick={() => void apply(plan)} disabled={busy !== null}>
                  <ListChecks aria-hidden="true" />
                  {busy === "apply" ? "Applying…" : "Use this edit"}
                </Button>
              )}
              <ButtonLink href={`${editorLink}?plan=${plan.id}`} variant="secondary" size="lg">
                <Pencil aria-hidden="true" />
                Edit choices
              </ButtonLink>
              <Button size="lg" variant="ghost" onClick={() => void another(plan)} disabled={busy !== null}>
                <Shuffle aria-hidden="true" />
                {busy === "regenerate" ? "Starting…" : "Try another plan"}
              </Button>
            </div>
          ) : null}
          {reviewing && plan?.status === "applied" && !plan.clip_edit_id ? (
            <p className="px-4 pb-4 text-xs text-subtle sm:px-6">
              The version made from this plan was deleted. Use “Edit choices” to open its settings in the editor, or try
              another plan.
            </p>
          ) : null}
          {reviewing && plan?.status === "ready" ? (
            <p className="flex items-center gap-1.5 px-4 pb-4 text-xs text-subtle sm:px-6">
              <ArrowRight aria-hidden="true" className="size-3" />
              “Use this edit” renders the short with these settings; you can still change them in the editor.
            </p>
          ) : null}
          {error ? (
            <div className="px-4 pb-4 sm:px-6">
              <InlineAlert title="That did not work">{error}</InlineAlert>
            </div>
          ) : null}
        </section>
        <aside aria-labelledby={`${id}-history`} className="min-w-0 space-y-3 self-start">
          <div className="flex items-center justify-between gap-2">
            <h2 id={`${id}-history`} className="text-sm font-medium text-muted">
              Plans{plans.length ? <span className="tabular text-subtle"> · {plans.length}</span> : null}
            </h2>
            {!composing ? (
              <Button size="sm" variant="ghost" onClick={() => setComposing(true)}>
                <Plus aria-hidden="true" />
                New plan
              </Button>
            ) : null}
          </div>
          {plans.length ? (
            <PlanHistory
              plans={plans}
              selectedId={composing ? null : (plan?.id ?? null)}
              onSelect={(p) => {
                setSelectedId(p.id);
                setComposing(false);
              }}
            />
          ) : (
            <p className="flex items-start gap-2 rounded-lg border border-dashed border-border px-3 py-3 text-xs text-subtle">
              <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
              No plans yet. Earlier plans stay here when you try another.
            </p>
          )}
        </aside>
      </div>
    </>
  );
}

/** /projects/[id]/clips/[clipId]/auto-edit — plan, review and apply an automatic first draft. */
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
        <PageHeader back={{ href: isProjectId(id) ? `/projects/${id}/clips` : "/projects", label: "Clips" }} title="Auto Edit" />
        {notFound ? (
          <EmptyState
            icon={Clapperboard}
            title="Clip not found"
            description="This clip does not exist or you do not have access to it."
            action={<ButtonLink href="/projects" variant="secondary">Back to projects</ButtonLink>}
          />
        ) : (
          <ErrorState title="Auto Edit could not be loaded" message={error ?? "Unavailable."} onRetry={reload} />
        )}
      </>
    );
  }
  if (data.clip.status !== "ready") {
    return (
      <>
        <PageHeader back={{ href: `/projects/${id}/clips`, label: "Clips" }} title="Auto Edit" />
        <EmptyState
          icon={Clapperboard}
          title="This clip isn't ready yet"
          description="Auto Edit starts from a rendered clip. Come back once it shows Ready."
          action={<ButtonLink href={`/projects/${id}/clips`} variant="secondary">Back to clips</ButtonLink>}
        />
      </>
    );
  }
  return <AutoEdit project={data.project} clip={data.clip} />;
}
