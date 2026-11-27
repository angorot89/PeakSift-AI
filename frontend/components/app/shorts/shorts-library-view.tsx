"use client";

import { Clapperboard, FolderOpen, LayoutGrid, List, ListChecks, Plus, Scissors, Search, SearchX } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { PageHeader } from "@/components/app/page-header";
import { ShortCard, ShortCardSkeleton, ShortRow, useShortAction } from "@/components/app/shorts/short-card";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { inputClasses } from "@/components/ui/input-styles";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { selectClasses } from "@/components/ui/select-styles";
import { useToast } from "@/components/ui/toast";
import {
  FILTERS,
  filterCounts,
  type FilterKey,
  getShorts,
  projectsOf,
  REVIEW_HREF,
  reviewQueue,
  type ShortItem,
  SORTS,
  type SortKey,
  visibleShorts,
} from "@/lib/shorts";
import { useApi } from "@/lib/use-api";

const GRID = "grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6";
const SEARCH_DELAY_MS = 200;

type Layout = "grid" | "list";
type View = { filter: FilterKey; sort: SortKey; q: string; project: string | null; layout: Layout };

function readParams(): View {
  const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
  const filter = FILTERS.find((f) => f.key === params.get("filter"))?.key ?? "all";
  const sort = SORTS.find((s) => s.key === params.get("sort"))?.key ?? "updated";
  const layout: Layout = params.get("view") === "list" ? "list" : "grid";
  return { filter, sort, q: params.get("q") ?? "", project: params.get("project"), layout };
}

/** The view lives in the URL (back, refresh and sharing keep it) without a navigation. */
function writeParams({ filter, sort, q, project, layout }: View) {
  const params = new URLSearchParams();
  if (filter !== "all") params.set("filter", filter);
  if (sort !== "updated") params.set("sort", sort);
  if (q.trim()) params.set("q", q.trim());
  if (project) params.set("project", project);
  if (layout === "list") params.set("view", "list");
  const query = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

/** Where "Create a Short" leads: the moments of the project worked on most recently. */
function createHref(items: ShortItem[]): string {
  return items[0] ? `/projects/${items[0].project.id}/clips` : "/projects";
}

function LibrarySkeleton() {
  return (
    <div role="status" aria-label="Loading your Shorts">
      <ul className={GRID}>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <ShortCardSkeleton key={i} />
        ))}
      </ul>
    </div>
  );
}

function Library({ items: loaded, truncated }: { items: ShortItem[]; truncated: boolean }) {
  const searchId = useId();
  const sortId = useId();
  const projectId = useId();
  const toast = useToast();
  const [view, setView] = useState(readParams);
  const { filter, sort, q, project, layout } = view;
  // Hiding or showing moves a card at once; the server already has the change.
  const [hiddenNow, setHiddenNow] = useState<Record<string, boolean>>({});
  const items = useMemo(
    () => loaded.map((item) => (item.id in hiddenNow ? { ...item, hidden: hiddenNow[item.id] } : item)),
    [loaded, hiddenNow],
  );
  const run = useShortAction(
    (item, hidden) => {
      setHiddenNow((now) => ({ ...now, [item.id]: hidden }));
      toast(hidden ? "Hidden. Find it under Hidden." : "Back in your library.");
    },
    (message) => toast(message),
  );
  const [query, setQuery] = useState(q);
  // The list follows the search box after a short pause, so typing stays smooth.
  useEffect(() => {
    const timer = window.setTimeout(() => setView((view) => ({ ...view, q: query })), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => writeParams(view), [view]);

  const counts = useMemo(() => filterCounts(items), [items]);
  const projects = useMemo(() => projectsOf(loaded), [loaded]);
  const shown = useMemo(() => visibleShorts(items, filter, q, sort, project), [items, filter, q, sort, project]);
  const narrowed = filter !== "all" || q.trim() !== "" || project !== null;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3">
        <SegmentedControl
          wrap
          label="Show"
          options={FILTERS.map((f) => ({ value: f.key, label: f.label, count: counts[f.key], dot: f.dot }))}
          value={filter}
          onChange={(value) => setView((view) => ({ ...view, filter: value }))}
        />
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <div className="relative sm:w-72 sm:flex-1 lg:max-w-sm">
            <label htmlFor={searchId} className="sr-only">
              Search Shorts
            </label>
            <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
            <input
              id={searchId}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by title or project"
              autoComplete="off"
              className={`${inputClasses} pl-9`}
            />
          </div>
          {projects.length > 1 ? (
            <div className="flex items-center gap-2">
              <label htmlFor={projectId} className="sr-only">
                Project
              </label>
              <select
                id={projectId}
                value={project ?? ""}
                onChange={(event) => setView((view) => ({ ...view, project: event.target.value || null }))}
                className={`${selectClasses} sm:w-48`}
              >
                <option value="">All projects</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <div className="flex items-center gap-2">
            <label htmlFor={sortId} className="shrink-0 text-small text-muted">
              Sort
            </label>
            <select
              id={sortId}
              value={sort}
              onChange={(event) => setView((view) => ({ ...view, sort: event.target.value as SortKey }))}
              className={`${selectClasses} sm:w-48`}
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div role="group" aria-label="Layout" className="inline-flex shrink-0 self-start rounded-control border border-border bg-surface-2 p-0.5 sm:self-auto">
            {([
              { value: "grid", label: "Grid", icon: LayoutGrid },
              { value: "list", label: "List", icon: List },
            ] as const).map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={layout === option.value}
                aria-label={`${option.label} view`}
                title={`${option.label} view`}
                onClick={() => setView((view) => ({ ...view, layout: option.value }))}
                className={`flex size-8 items-center justify-center rounded-[0.375rem] transition-colors focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:size-11 ${
                  layout === option.value ? "bg-background text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]" : "text-muted hover:text-foreground"
                }`}
              >
                <option.icon aria-hidden="true" className="size-4" />
              </button>
            ))}
          </div>
        </div>
      </div>

      <p role="status" aria-live="polite" className="sr-only">
        {shown.length === 1 ? "1 Short" : `${shown.length} Shorts`}
        {narrowed ? " match" : ""}
      </p>

      {shown.length ? (
        layout === "list" ? (
          <ul className="space-y-2">
            {shown.map((item) => (
              <ShortRow key={item.id} item={item} run={run} />
            ))}
          </ul>
        ) : (
          <ul className={GRID}>
            {shown.map((item) => (
              <ShortCard key={item.id} item={item} run={run} />
            ))}
          </ul>
        )
      ) : (
        <EmptyState
          icon={SearchX}
          title="No Shorts match"
          description={q.trim() ? `Nothing matches “${q.trim()}”${filter !== "all" ? " in this view" : ""}.` : "No Shorts are in this view right now."}
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setQuery("");
                setView({ ...view, filter: "all", q: "", project: null });
              }}
            >
              Show all Shorts
            </Button>
          }
        />
      )}
      {truncated ? <p className="text-small text-subtle">Showing your 500 most recently updated Shorts.</p> : null}
    </div>
  );
}

/** /shorts: everything the creator has made, ready to edit, publish or review. */
export function ShortsLibraryView() {
  const { data, error, loading, reload } = useApi(getShorts);
  const items = data?.shorts ?? [];
  const waiting = reviewQueue(items).length;
  return (
    <>
      <PageHeader
        size="hero"
        title="Shorts"
        description="Everything you've created, ready to edit, publish or review."
        action={
          <div className="flex flex-wrap gap-2">
            {waiting ? (
              <ButtonLink href={REVIEW_HREF} variant="secondary">
                <ListChecks aria-hidden="true" />
                Review & post ({waiting})
              </ButtonLink>
            ) : null}
            <ButtonLink href={createHref(items)}>
              <Plus aria-hidden="true" />
              Create a Short
            </ButtonLink>
          </div>
        }
      />
      {loading && !data ? (
        <LibrarySkeleton />
      ) : error || !data ? (
        <ErrorState title="Your Shorts couldn't be loaded" message={error ?? "Try again."} onRetry={reload} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Clapperboard}
          title="No Shorts yet"
          description="Find a moment in one of your projects and turn it into a Short."
          action={
            <>
              <ButtonLink href="/projects">
                <FolderOpen aria-hidden="true" />
                Open projects
              </ButtonLink>
              <ButtonLink href="/projects/new" variant="secondary">
                <Scissors aria-hidden="true" />
                Create project
              </ButtonLink>
            </>
          }
        />
      ) : (
        <Library items={items} truncated={data.truncated} />
      )}
    </>
  );
}
