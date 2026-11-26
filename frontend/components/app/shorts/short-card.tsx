"use client";

import { CalendarClock, CirclePlay, Download, Eye, EyeOff, FolderOpen, MoreHorizontal, Pencil, Send, Smartphone, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { StatusPill } from "@/components/ui/status-pill";
import { FrameTag, VideoFrame } from "@/components/ui/video-frame";
import { errorMessage } from "@/lib/api";
import { clipContentUrl } from "@/lib/clips";
import { editContentUrl, editDownloadUrl } from "@/lib/edits";
import {
  analyticsHref,
  cardLabel,
  clock,
  contextLine,
  continueHref,
  editorHref,
  menuActions,
  quickActions,
  setShortHidden,
  shortHref,
  type ShortAction,
  type ShortItem,
  statusLabel,
} from "@/lib/shorts";

/** The owner-checked media a Short can show: its render, or the moment's cut until then. */
export function previewSrc(item: Pick<ShortItem, "preview" | "edit_id" | "clip_id">): string | null {
  if (item.preview === "short" && item.edit_id) return editContentUrl(item.edit_id);
  if (item.preview === "clip") return clipContentUrl(item.clip_id);
  return null;
}

/** A still a little into the Short (past a fade-in), never past its end. */
export const previewAt = (item: Pick<ShortItem, "duration_seconds">) => Math.min(2, (item.duration_seconds ?? 2) / 3);

const ICONS: Record<ShortAction, typeof Pencil> = {
  continue: Pencil,
  edit: Pencil,
  download: Download,
  publish: Send,
  analytics: TrendingUp,
  project: FolderOpen,
  performance: TrendingUp,
  fix_render: Pencil,
  fix_publish: Send,
  retry_cut: FolderOpen,
  schedule: CalendarClock,
  hide: EyeOff,
  show: Eye,
};

/**
 * Runs one of a Short's actions (the library's menu and the detail page share it). Hiding and
 * showing call the server, then `onHidden` so the page can move the card.
 */
export function useShortAction(onHidden?: (item: ShortItem, hidden: boolean) => void, onError?: (message: string) => void) {
  const router = useRouter();
  return (item: ShortItem, action: ShortAction) => {
    switch (action) {
      case "hide":
      case "show": {
        const hidden = action === "hide";
        void setShortHidden(item.id, hidden).then(
          () => onHidden?.(item, hidden),
          (error) => onError?.(errorMessage(error)),
        );
        return;
      }
      case "schedule":
        return router.push(`${shortHref(item.id)}#publishing`);
      case "continue":
        return router.push(continueHref(item));
      case "edit":
      case "fix_render":
        return router.push(editorHref(item));
      case "download":
        if (item.edit_id) window.location.assign(editDownloadUrl(item.edit_id));
        return;
      case "publish":
      case "fix_publish":
        return router.push(`${shortHref(item.id)}#publishing`);
      case "analytics":
      case "performance":
        return item.performance ? router.push(analyticsHref(item.performance.content_id)) : router.push(`${shortHref(item.id)}#performance`);
      case "retry_cut":
        return router.push(`/projects/${item.project.id}/clips`);
      case "project":
        return router.push(`/projects/${item.project.id}`);
    }
  };
}

type Run = (item: ShortItem, action: ShortAction) => void;

/** The card's always-visible buttons (Publish, Schedule, Download…), next to the card link. */
function QuickActions({ item, run, compact = false }: { item: ShortItem; run: Run; compact?: boolean }) {
  const [busy, setBusy] = useState<ShortAction | null>(null);
  const actions = quickActions(item);
  if (!actions.length) return null;
  return (
    <span className={`flex flex-wrap gap-1.5 ${compact ? "" : "mt-2.5"}`}>
      {actions.map(({ action, label }) => {
        const Icon = ICONS[action];
        return (
          <button
            key={action}
            type="button"
            disabled={busy !== null}
            onClick={() => {
              setBusy(action);
              run(item, action);
              window.setTimeout(() => setBusy(null), 600);
            }}
            aria-label={`${label}: ${item.title}`}
            className={`inline-flex h-8 items-center gap-1.5 rounded-control border px-2.5 text-caption font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60 pointer-coarse:h-11 ${
              action === "publish" ? "border-accent-fill bg-accent-fill text-accent-ink hover:bg-accent-fill-hover" : "border-border-strong bg-surface-2 text-foreground hover:bg-surface-3"
            }`}
          >
            <Icon aria-hidden="true" className="size-3.5" />
            {label}
          </button>
        );
      })}
    </span>
  );
}

function menuItems(item: ShortItem, run: Run): MenuItem[] {
  return menuActions(item).map(({ action, label }) => ({ label, icon: ICONS[action], onSelect: () => run(item, action) }));
}

/** One Short in the library: the whole card opens it; quick actions and the menu sit beside it. */
export function ShortCard({ item, run }: { item: ShortItem; run: Run }) {
  const status = statusLabel(item.status);
  const youtube = item.publish.platform === "youtube" && (item.status === "published" || item.status === "on_youtube" || item.status === "publishing");
  return (
    <li className={`group/card @container relative min-w-0 ${item.hidden ? "opacity-70" : ""}`}>
      <Link
        href={shortHref(item.id)}
        aria-label={cardLabel(item)}
        className="block rounded-card transition-transform duration-200 ease-out-soft hover:-translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none motion-reduce:hover:translate-y-0"
      >
        <VideoFrame
          src={previewSrc(item)}
          at={previewAt(item)}
          ratio="vertical"
          icon={Smartphone}
          className="rounded-card border border-border shadow-card transition-[border-color] group-hover/card:border-border-strong"
        >
          <span className="absolute top-2 left-2 flex flex-col items-start gap-1">
            <StatusPill tone={status.tone} overlay>
              {status.label}
            </StatusPill>
            {item.schedule ? (
              <StatusPill tone="waiting" overlay>
                Scheduled
              </StatusPill>
            ) : null}
            {item.hidden ? (
              <StatusPill tone="neutral" overlay>
                Hidden
              </StatusPill>
            ) : null}
          </span>
          {item.version && item.version.count > 1 ? (
            <FrameTag className="bottom-2 left-2">
              v{item.version.number}
              <span className="sr-only"> of {item.version.count}</span>
            </FrameTag>
          ) : null}
          {item.duration_seconds ? <FrameTag className="right-2 bottom-2">{clock(item.duration_seconds)}</FrameTag> : null}
        </VideoFrame>
        <span aria-hidden="true" className="mt-2.5 block pr-8 pointer-coarse:pr-10">
          <span className="line-clamp-2 text-sm font-medium text-pretty break-words text-foreground">{item.title}</span>
          <span className="mt-0.5 block truncate text-caption text-subtle">{item.project.name}</span>
          <span className="mt-1 flex items-start gap-1 text-caption text-muted">
            {youtube ? <CirclePlay className="mt-px size-3.5 shrink-0 text-subtle" /> : null}
            {item.schedule ? <CalendarClock className="mt-px size-3.5 shrink-0 text-subtle" /> : null}
            <span className="line-clamp-2">{contextLine(item)}</span>
          </span>
        </span>
      </Link>
      <QuickActions item={item} run={run} />
      {/* Beside the title, just under the 9:16 frame (100cqw × 16/9 is the frame's height): next
          to the card link, not inside it, and always visible — no hover needed. */}
      <div className="absolute top-[calc(100cqw*16/9+0.375rem)] -right-1.5">
        <Menu label={`Actions for ${item.title}`} trigger={<MoreHorizontal aria-hidden="true" />} items={menuItems(item, run)} />
      </div>
    </li>
  );
}

/** The same Short as one row of the list view: frame, title, project, status, length, actions. */
export function ShortRow({ item, run }: { item: ShortItem; run: Run }) {
  const status = statusLabel(item.status);
  return (
    <li className={`relative flex items-center gap-4 rounded-card border border-border bg-surface p-3 transition-colors hover:border-border-strong ${item.hidden ? "opacity-70" : ""}`}>
      <Link href={shortHref(item.id)} aria-label={cardLabel(item)} className="flex min-w-0 flex-1 items-center gap-4 rounded-control focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <VideoFrame src={previewSrc(item)} at={previewAt(item)} ratio="vertical" icon={Smartphone} className="w-14 shrink-0 rounded-block border border-border sm:w-16" />
        <span aria-hidden="true" className="min-w-0 flex-1">
          <span className="block truncate font-medium text-foreground">{item.title}</span>
          <span className="mt-0.5 block truncate text-small text-subtle">
            {item.project.name}
            {item.duration_seconds ? ` · ${clock(item.duration_seconds)}` : ""}
          </span>
          <span className="mt-1 block truncate text-small text-muted">{contextLine(item)}</span>
        </span>
        <span aria-hidden="true" className="hidden flex-col items-end gap-1 sm:flex">
          <StatusPill tone={status.tone}>{status.label}</StatusPill>
          {item.schedule ? <StatusPill tone="waiting">Scheduled</StatusPill> : null}
          {item.hidden ? <StatusPill tone="neutral">Hidden</StatusPill> : null}
        </span>
      </Link>
      <span className="hidden md:block">
        <QuickActions item={item} run={run} compact />
      </span>
      <Menu label={`Actions for ${item.title}`} trigger={<MoreHorizontal aria-hidden="true" />} items={menuItems(item, run)} />
    </li>
  );
}

/** The placeholder card while the library loads (same proportions: nothing shifts). */
export function ShortCardSkeleton() {
  return (
    <li aria-hidden="true" className="min-w-0">
      <span className="block aspect-[9/16] animate-pulse rounded-card bg-white/[0.05] motion-reduce:animate-none" />
      <span className="mt-2.5 block h-4 w-4/5 animate-pulse rounded bg-white/[0.05] motion-reduce:animate-none" />
      <span className="mt-1.5 block h-3 w-1/2 animate-pulse rounded bg-white/[0.04] motion-reduce:animate-none" />
    </li>
  );
}

