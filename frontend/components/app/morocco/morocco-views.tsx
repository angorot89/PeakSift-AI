"use client";

import {
  ArrowRight,
  Globe,
  ImageIcon,
  Languages,
  MessageSquareQuote,
  Music,
  Plus,
  Search,
  Shapes,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/app/page-header";
import { ErrorState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { ButtonLink } from "@/components/ui/button-link";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { inputClasses } from "@/components/ui/input-styles";
import { SectionHeader } from "@/components/ui/section-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { errorMessage } from "@/lib/api";
import { labelLine, labelsOf } from "@/lib/asset-labels";
import { listTemplates, listTemplateStarters } from "@/lib/brand";
import { getLocalAssets, getMarkets, setDefaultMarket, type KitAsset, type Markets } from "@/lib/markets";
import { defaultMode, defaultModeLabel, KIT_TABS, kitFilters, kitMatches, kitTab, MODES, MOROCCO_SECTIONS, type KitTab, type MoroccoSectionKey } from "@/lib/morocco";
import { useApi } from "@/lib/use-api";
import { visualThumbnailUrl } from "@/lib/visuals";

const ICONS: Record<MoroccoSectionKey, LucideIcon> = {
  darija_hooks: MessageSquareQuote,
  local_templates: Shapes,
  local_assets: ImageIcon,
  local_sounds: Music,
  ask: Sparkles,
};

const loadVisuals = () => getLocalAssets("ma", "visual");
const loadSounds = () => getLocalAssets("ma", "audio");
const loadFormats = () => listTemplateStarters("ma");

/** Global or Morocco Mode: saves the creator's default market for new projects (it never changes
 * existing projects or Shorts) and opens that mode. Morocco Mode always includes Global. */
export function ModeSwitch({ current }: { current: "global" | "morocco" }) {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const saved = defaultMode(user?.default_market);
  async function choose(mode: (typeof MODES)[number]) {
    if (mode.key === current && mode.key === saved) return;
    setBusy(mode.key);
    setError(null);
    try {
      // Saves the default for new projects (existing projects never change), then opens the mode.
      if (mode.key !== saved) setUser(await setDefaultMarket(mode.market));
      if (mode.key !== current) router.push(mode.href);
      setBusy(null);
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(null);
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div role="group" aria-label="Mode" className="inline-flex gap-1 rounded-block border border-border bg-surface/80 p-1">
        {MODES.map((mode) => (
          <button
            key={mode.key}
            type="button"
            aria-pressed={current === mode.key}
            disabled={busy !== null}
            onClick={() => void choose(mode)}
            className={`inline-flex min-h-11 items-center gap-2 rounded-control px-4 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait ${
              current === mode.key ? "bg-accent/[0.14] text-foreground shadow-[inset_0_0_0_1px_rgb(249_115_22/0.45)]" : "text-muted hover:text-foreground"
            }`}
          >
            {mode.key === "global" ? <Globe aria-hidden="true" className="size-4" /> : <Languages aria-hidden="true" className="size-4" />}
            {mode.label}
          </button>
        ))}
      </div>
      <StatusPill tone="success">Global library included</StatusPill>
      <p className="text-small text-muted">New projects: {defaultModeLabel(saved)}</p>
      {error ? <p role="alert" className="text-small text-rose-300">{error}</p> : null}
    </div>
  );
}

function SectionCard({ item }: { item: (typeof MOROCCO_SECTIONS)[number] }) {
  const Icon = ICONS[item.key];
  return (
    <li className="min-w-0">
      <Card className="flex h-full flex-col gap-3">
        <span aria-hidden="true" className="flex size-11 items-center justify-center rounded-block bg-accent/12 text-accent-soft">
          <Icon className="size-5" />
        </span>
        <div>
          <h3 className="text-title">{item.title}</h3>
          <p className="mt-1 text-sm text-pretty text-muted">{item.promise}</p>
        </div>
        <Link
          href={item.href}
          className="mt-auto inline-flex min-h-11 items-center gap-1.5 text-small font-medium text-accent-soft hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {item.cta}
          <ArrowRight aria-hidden="true" className="size-4 shrink-0" />
        </Link>
      </Card>
    </li>
  );
}

function GlobalIncluded() {
  const links = [
    { href: "/projects", label: "Your projects and moments" },
    { href: "/brand", label: "Global templates and brands" },
    { href: "/shorts", label: "Your Shorts" },
  ];
  return (
    <Card>
      <div className="flex items-start gap-4">
        <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-block bg-success/15 text-emerald-200">
          <Globe className="size-5" />
        </span>
        <div className="min-w-0">
          <h2 className="text-section">Browse the Global library</h2>
          <p className="mt-1 text-sm text-pretty text-muted">
            Morocco Mode adds Moroccan context on top of Global — it never replaces it. Every visual, sound, template and tool
            you use in Global works here, and Global alternatives appear right after local matches.
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {links.map((link) => (
              <li key={link.href}>
                <ButtonLink href={link.href} variant="secondary" size="sm">
                  {link.label}
                </ButtonLink>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function names(vocab: Markets | null, family: "visual" | "audio") {
  const list = family === "visual" ? vocab?.visual_categories : vocab?.audio_categories;
  return Object.fromEntries((list ?? []).map((c) => [c.code, c.label]));
}

/** Your Moroccan visuals: real thumbnails, or an honest empty state with what to do. */
function LocalVisuals({ assets, vocab, limit }: { assets: KitAsset[]; vocab: Markets | null; limit?: number }) {
  if (!assets.length) {
    return (
      <EmptyState
        icon={ImageIcon}
        title="No Moroccan visuals yet"
        description="Open a visual you made, own or licensed in a project's Assets and set its market to Moroccan. Your Global visuals stay available."
        action={
          <>
            <ButtonLink href="/projects">Open a project</ButtonLink>
            <ButtonLink href="/projects" variant="secondary">Browse Global library</ButtonLink>
          </>
        }
      />
    );
  }
  const categories = names(vocab, "visual");
  const origins = Object.fromEntries((vocab?.asset_origins ?? []).map((o) => [o.code, o.label]));
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {assets.slice(0, limit).map((asset) => (
        <li key={asset.id} className="min-w-0">
          <Link
            href={`/projects/${asset.project.id}/assets`}
            className="group block rounded-block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span className="block aspect-video overflow-hidden rounded-block border border-border bg-surface-2">
              {asset.has_thumbnail ? (
                // eslint-disable-next-line @next/next/no-img-element -- owner-checked private thumbnail stream
                <img src={visualThumbnailUrl(asset.project.id, asset.id)} alt="" loading="lazy" className="size-full object-cover" />
              ) : (
                <span className="flex size-full items-center justify-center text-subtle"><ImageIcon aria-hidden="true" className="size-6" /></span>
              )}
            </span>
            <span dir="auto" className="mt-2 block truncate text-sm font-medium text-foreground">{asset.display_name}</span>
            <span className="block truncate text-caption text-subtle">
              {labelLine(labelsOf({ ...asset, market: "global" }), { localLabel: null, categories, origins }) || asset.project.name}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function LocalSounds({ assets, vocab, limit }: { assets: KitAsset[]; vocab: Markets | null; limit?: number }) {
  if (!assets.length) {
    return (
      <EmptyState
        icon={Music}
        title="No Moroccan sound assets have been added yet"
        description="Upload sounds you recorded, own or licensed to a project, then set their market to Moroccan under Assets → Sounds. PeakSift never adds music or sounds for you."
        action={
          <>
            <ButtonLink href="/projects">Upload sound</ButtonLink>
            <ButtonLink href="/projects" variant="secondary">Browse Global sounds</ButtonLink>
          </>
        }
      />
    );
  }
  const categories = names(vocab, "audio");
  const origins = Object.fromEntries((vocab?.asset_origins ?? []).map((o) => [o.code, o.label]));
  return (
    <ul className="divide-y divide-border rounded-block border border-border">
      {assets.slice(0, limit).map((asset) => (
        <li key={asset.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <span className="min-w-0">
            <span dir="auto" className="block truncate text-sm font-medium text-foreground">{asset.display_name}</span>
            <span className="block text-caption text-subtle">
              {[asset.category ? categories[asset.category] : null, origins[asset.origin], asset.duration_seconds ? `${asset.duration_seconds.toFixed(1)} s` : null]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </span>
          <Link href={`/projects/${asset.project.id}`} className="inline-flex min-h-11 items-center text-small text-muted hover:text-foreground">
            {asset.project.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Formats({ limit }: { limit?: number }) {
  const { data: starters, error } = useApi(loadFormats);
  const { data: mine } = useApi(listTemplates);
  if (error) return <ErrorState title="The formats couldn't be loaded" message={error} />;
  if (!starters) return <Skeleton className="h-40 rounded-card" />;
  const formats = starters.filter((s) => s.market === "ma").slice(0, limit);
  const yours = (mine ?? []).filter((t) => t.market === "ma");
  return (
    <div className="space-y-4">
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {formats.map((format) => (
          <li key={format.key} className="min-w-0">
            <Card className="flex h-full flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-title">{format.label}</h3>
                <StatusPill tone="neutral">Curated</StatusPill>
              </div>
              <p className="text-sm text-pretty text-muted">{format.description}</p>
              <ButtonLink href={`/brand/templates/new?start=${format.key}`} variant="secondary" size="sm" className="mt-auto self-start">
                Use this format
              </ButtonLink>
            </Card>
          </li>
        ))}
      </ul>
      {yours.length ? (
        <p className="text-sm text-muted">
          Your Morocco templates: {yours.map((t) => `“${t.name}”`).join(", ")}. <Link href="/brand" className="text-accent-soft underline-offset-4 hover:underline">Open Brand Studio</Link>
        </p>
      ) : null}
      <p className="text-small text-subtle">Curated by PeakSift from settings it already has — not trends. Global templates stay available in Brand Studio.</p>
    </div>
  );
}

/** /morocco: Morocco Mode's front page — what is real today, with Global always one click away. */
export function MoroccoHomeView() {
  const visuals = useApi(loadVisuals);
  const sounds = useApi(loadSounds);
  const { data: vocab } = useApi(getMarkets);
  return (
    <>
      <PageHeader
        size="hero"
        title="Morocco Mode"
        description="PeakSift with Moroccan context — on top of everything in Global."
        action={
          <ButtonLink href="/projects/new?market=ma">
            <Plus aria-hidden="true" />
            Create in Morocco Mode
          </ButtonLink>
        }
      >
        <div className="mt-6">
          <ModeSwitch current="morocco" />
        </div>
      </PageHeader>
      <div className="space-y-12">
        <section aria-labelledby="morocco-adds-heading">
          <SectionHeader id="morocco-adds-heading" title="What Morocco Mode adds" description="Darija in any script, mixed with French or English — your language stays yours." />
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {MOROCCO_SECTIONS.map((item) => (
              <SectionCard key={item.key} item={item} />
            ))}
          </ul>
        </section>
        <section aria-labelledby="formats-heading">
          <SectionHeader id="formats-heading" title="Explore Morocco content styles" description="Curated formats you can start a template from." />
          <Formats limit={3} />
        </section>
        <section aria-labelledby="local-visuals-heading">
          <SectionHeader
            id="local-visuals-heading"
            title="Your Moroccan visuals"
            actions={<ButtonLink href="/morocco/kit?tab=visuals" variant="ghost" size="sm">Open Creator Kit</ButtonLink>}
          />
          {visuals.error ? (
            <ErrorState title="Your visuals couldn't be loaded" message={visuals.error} onRetry={visuals.reload} />
          ) : visuals.data ? (
            <LocalVisuals assets={visuals.data.assets} vocab={vocab} limit={8} />
          ) : (
            <Skeleton className="h-32 rounded-card" />
          )}
        </section>
        <section aria-labelledby="local-sounds-heading">
          <SectionHeader id="local-sounds-heading" title="Local sounds" />
          {sounds.error ? (
            <ErrorState title="Your sounds couldn't be loaded" message={sounds.error} onRetry={sounds.reload} />
          ) : sounds.data ? (
            <LocalSounds assets={sounds.data.assets} vocab={vocab} limit={6} />
          ) : (
            <Skeleton className="h-24 rounded-card" />
          )}
        </section>
        <GlobalIncluded />
      </div>
    </>
  );
}

/** /morocco/kit: the creator's own local library — visuals, sounds, hooks and templates. */
export function CreatorKitView() {
  const params = useSearchParams();
  const router = useRouter();
  const [tab, setTab] = useState<KitTab>(kitTab(params.get("tab")));
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const visuals = useApi(loadVisuals);
  const sounds = useApi(loadSounds);
  const { data: vocab } = useApi(getMarkets);
  const family = tab === "sounds" ? "audio" : "visual";
  const source = tab === "sounds" ? sounds : visuals;
  const categoryNames = useMemo(() => names(vocab, family), [vocab, family]);
  const filters = source.data ? kitFilters(source.data.assets, categoryNames) : [];
  const shown = (source.data?.assets ?? []).filter((asset) => kitMatches(asset, query, filter, categoryNames));
  return (
    <>
      <PageHeader title="Morocco Creator Kit" back={{ href: "/morocco", label: "Morocco Mode" }} description="Your own Moroccan visuals and sounds, Darija hooks and Morocco formats. Global stays available everywhere." />
      <div className="space-y-6">
        <SegmentedControl
          wrap
          label="Kit"
          options={KIT_TABS.map((t) => ({ value: t.key, label: t.label }))}
          value={tab}
          onChange={(value) => {
            setTab(value);
            setFilter(null);
            router.replace(`/morocco/kit?tab=${value}`, { scroll: false });
          }}
        />
        {tab === "visuals" || tab === "sounds" ? (
          <>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative sm:w-80">
                <label htmlFor="kit-search" className="sr-only">Search the kit</label>
                <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
                <input id="kit-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search names, tags, places" className={`${inputClasses} pl-9`} />
              </div>
              {filters.length ? (
                <SegmentedControl
                  wrap
                  size="sm"
                  label="Filter"
                  options={[{ value: "", label: "All" }, ...filters.map((f) => ({ value: f.key, label: f.label }))]}
                  value={filter ?? ""}
                  onChange={(value) => setFilter(value || null)}
                />
              ) : null}
            </div>
            {source.error ? (
              <ErrorState title="Your kit couldn't be loaded" message={source.error} onRetry={source.reload} />
            ) : !source.data ? (
              <Skeleton className="h-40 rounded-card" />
            ) : source.data.assets.length && !shown.length ? (
              <p className="text-sm text-muted">Nothing in your kit matches. Clear the search or the filter.</p>
            ) : tab === "visuals" ? (
              <LocalVisuals assets={shown} vocab={vocab} />
            ) : (
              <LocalSounds assets={shown} vocab={vocab} />
            )}
          </>
        ) : tab === "hooks" ? (
          <Card>
            <h2 className="text-section">Darija hooks come from your words</h2>
            <p className="mt-2 text-sm text-pretty text-muted">
              Open a Short in the editor and choose <strong className="font-medium text-foreground">Opening → Hook ideas</strong>: PeakSift offers your
              clip&apos;s own lines — a question, a reaction, a lesson — and can show your Darija in Arabic script or Latin letters. It never writes
              Darija you didn&apos;t say: the local assistant&apos;s Darija isn&apos;t reliable enough yet.
            </p>
            <ButtonLink href="/shorts" variant="secondary" size="sm" className="mt-4">Open your Shorts</ButtonLink>
          </Card>
        ) : (
          <Formats />
        )}
        <GlobalIncluded />
      </div>
    </>
  );
}
