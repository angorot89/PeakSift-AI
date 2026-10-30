"use client";

import {
  ArrowRight,
  Clock,
  Globe,
  ImageIcon,
  Languages,
  MessageSquareQuote,
  Music,
  Shapes,
  Sparkles,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/app/page-header";
import { ButtonLink } from "@/components/ui/button-link";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineAlert } from "@/components/ui/inline-alert";
import { SectionHeader } from "@/components/ui/section-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatusPill } from "@/components/ui/status-pill";
import { capability, KIT_TABS, MOROCCO_CAPABILITIES, type KitTab, type MoroccoCapability, type MoroccoCapabilityKey } from "@/lib/morocco";

const ICONS: Record<MoroccoCapabilityKey, LucideIcon> = {
  darija_hooks: MessageSquareQuote,
  local_sounds: Music,
  local_trends: TrendingUp,
  local_templates: Shapes,
  local_assets: ImageIcon,
  clip_suggestions: Sparkles,
};

/** Global or Morocco Mode — and Morocco Mode always includes the global library. */
export function ModeSwitch({ current }: { current: "global" | "morocco" }) {
  const option = (mode: "global" | "morocco", href: string, label: string) => (
    <Link
      href={href}
      aria-current={current === mode ? "page" : undefined}
      className={`inline-flex min-h-11 items-center gap-2 rounded-control px-4 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
        current === mode ? "bg-accent/[0.14] text-foreground shadow-[inset_0_0_0_1px_rgb(249_115_22/0.45)]" : "text-muted hover:text-foreground"
      }`}
    >
      {mode === "global" ? <Globe aria-hidden="true" className="size-4" /> : <Languages aria-hidden="true" className="size-4" />}
      {label}
    </Link>
  );
  return (
    <div className="flex flex-wrap items-center gap-3">
      <nav aria-label="Mode" className="inline-flex gap-1 rounded-block border border-border bg-surface/80 p-1">
        {option("global", "/home", "Global")}
        {option("morocco", "/morocco", "Morocco Mode")}
      </nav>
      <StatusPill tone="success">Global library included</StatusPill>
    </div>
  );
}

function PreviewNotice() {
  return (
    <InlineAlert tone="info" title="Morocco Mode is a preview">
      Its Moroccan hooks, sounds, visuals and suggestions are not available yet — nothing here is generated or invented.
      Every Global tool keeps working as usual.
    </InlineAlert>
  );
}

/** One Morocco capability: what it will do, that it is not available yet, and what works today. */
function CapabilityCard({ item }: { item: MoroccoCapability }) {
  const Icon = ICONS[item.key];
  return (
    <li className="min-w-0">
      <Card className="flex h-full flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-block bg-accent/12 text-accent-soft">
            <Icon className="size-5" />
          </span>
          {item.available ? null : <StatusPill tone="waiting">Not available yet</StatusPill>}
        </div>
        <div>
          <h3 className="text-title">{item.title}</h3>
          <p className="mt-1 text-sm text-pretty text-muted">{item.promise}</p>
        </div>
        {item.today ? (
          <Link
            href={item.today.href}
            className="mt-auto inline-flex min-h-11 items-center gap-1.5 text-small font-medium text-accent-soft hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Today: {item.today.label}
            <ArrowRight aria-hidden="true" className="size-4 shrink-0" />
          </Link>
        ) : (
          <p className="mt-auto flex items-center gap-1.5 text-small text-subtle">
            <Clock aria-hidden="true" className="size-4 shrink-0" />
            Shown only once PeakSift has real data for it.
          </p>
        )}
      </Card>
    </li>
  );
}

function GlobalIncluded() {
  const links = [
    { href: "/projects", label: "Your projects and moments" },
    { href: "/brand", label: "Your brands and templates" },
    { href: "/analytics", label: "Your analytics" },
  ];
  return (
    <Card className="next-glow border-accent/30">
      <div className="flex items-start gap-4">
        <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-block bg-success/15 text-emerald-200">
          <Globe className="size-5" />
        </span>
        <div className="min-w-0">
          <h2 className="text-section">Everything in Global stays yours</h2>
          <p className="mt-1 text-sm text-pretty text-muted">
            Morocco Mode adds Moroccan context on top of Global — it never replaces it. Your projects, brands, templates,
            visuals and Ask PeakSift work exactly as they do in Global.
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

/** What already works for Moroccan content today, without Morocco Mode. */
function DarijaToday() {
  return (
    <Card>
      <h2 className="text-section">Darija in your Shorts today</h2>
      <ul className="mt-3 space-y-2 text-sm text-pretty text-muted">
        <li>
          Captions show Arabic script right to left, and mixed Arabic, French and Latin-letter Darija on the same line.
        </li>
        <li>Your opening hook can be written in Arabic script or Latin letters.</li>
        <li>
          Transcription of Darija, code-switching and Moroccan names has not been measured yet — check your transcript
          before you rely on it.
        </li>
      </ul>
      <p dir="rtl" lang="ar" className="mt-4 rounded-block border border-border bg-surface-2/60 px-4 py-3 text-right text-sm text-muted">
        <span className="sr-only">Right-to-left text sample: </span>
        هاد النص كيبان من اليمين لليسار
      </p>
    </Card>
  );
}

/** /morocco — Morocco Mode's home (preview). */
export function MoroccoHomeView() {
  return (
    <div className="space-y-10">
      <PageHeader
        size="hero"
        title={
          <>
            Create Shorts for <span className="text-accent-soft">Morocco</span>
          </>
        }
        description="Darija, local culture and Moroccan audiences — on top of everything you already have in Global."
        action={
          <ButtonLink href="/morocco/kit" variant="secondary">
            Open the Creator Kit
          </ButtonLink>
        }
      >
        <div className="mt-6">
          <ModeSwitch current="morocco" />
        </div>
      </PageHeader>
      <PreviewNotice />
      <section aria-labelledby="coming-heading">
        <SectionHeader id="coming-heading" title="What Morocco Mode adds" description="Each part turns on only when it has real Moroccan data behind it." />
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {MOROCCO_CAPABILITIES.map((item) => (
            <CapabilityCard key={item.key} item={item} />
          ))}
        </ul>
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <GlobalIncluded />
        <DarijaToday />
      </div>
    </div>
  );
}

/** /morocco/kit — the Morocco Creator Kit (preview): local library, suggestions, local + global. */
export function CreatorKitView() {
  const [tab, setTab] = useState<KitTab>("images");
  const current = KIT_TABS.find((t) => t.key === tab)!;
  const need = capability(current.needs);
  const suggestions = [capability("clip_suggestions"), capability("darija_hooks")];
  return (
    <div className="space-y-10">
      <PageHeader
        size="hero"
        title="Morocco Creator Kit"
        description="Local hooks, visuals, sounds and suggestions for Moroccan creators — with your global library always one click away."
        back={{ href: "/morocco", label: "Morocco Mode" }}
      >
        <div className="mt-6">
          <ModeSwitch current="morocco" />
        </div>
      </PageHeader>
      <PreviewNotice />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section aria-labelledby="kit-library-heading" className="min-w-0">
          <Card>
            <SectionHeader id="kit-library-heading" title="Local library" description="Moroccan images, B-roll, sounds, hooks and templates." />
            <SegmentedControl label="Library" options={KIT_TABS.map((t) => ({ value: t.key, label: t.label }))} value={tab} onChange={setTab} />
            <div className="mt-5">
              <EmptyState
                icon={ICONS[current.needs]}
                title={`No Moroccan ${current.label === "B-roll" ? "B-roll" : current.label.toLowerCase()} yet`}
                description={need.promise}
                action={
                  need.today ? (
                    <ButtonLink href={need.today.href} variant="secondary">
                      {need.today.label}
                    </ButtonLink>
                  ) : undefined
                }
              />
            </div>
          </Card>
        </section>
        <aside aria-labelledby="kit-suggest-heading" className="space-y-4">
          <h2 id="kit-suggest-heading" className="text-section">
            Suggestions for your clip
          </h2>
          <ul className="space-y-4">
            {suggestions.map((item) => (
              <CapabilityCard key={item.key} item={item} />
            ))}
          </ul>
        </aside>
      </div>
      <section aria-labelledby="kit-match-heading">
        <Card>
          <SectionHeader
            id="kit-match-heading"
            title="Local + global match"
            description="When a visual is needed, Moroccan matches come first and global alternatives follow — you are never limited to one."
          />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-block border border-dashed border-border-strong p-4">
              <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Languages aria-hidden="true" className="size-4 text-accent-soft" /> Moroccan matches
              </p>
              <p className="mt-1 text-sm text-muted">Not available yet: there is no Moroccan library to match against.</p>
            </div>
            <div className="rounded-block border border-border bg-surface-2/60 p-4">
              <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Globe aria-hidden="true" className="size-4 text-emerald-200" /> Global alternatives
              </p>
              <p className="mt-1 text-sm text-muted">Your own visuals, searched by what they show, in each project&apos;s Assets.</p>
              <Link href="/projects" className="mt-2 inline-flex min-h-11 items-center gap-1.5 text-small font-medium text-accent-soft hover:underline">
                Go to your projects <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
