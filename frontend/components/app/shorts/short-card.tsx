"use client";

import { CirclePlay, Download, FolderOpen, MoreHorizontal, Pencil, Send, Smartphone, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { StatusPill } from "@/components/ui/status-pill";
import { FrameTag, VideoFrame } from "@/components/ui/video-frame";
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
};

/** Runs one of a Short's actions (the library's menu and the detail page share it). */
export function useShortAction() {
  const router = useRouter();
  return (item: ShortItem, action: ShortAction) => {
    switch (action) {
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

/** One Short in the library: the whole card opens it; the menu offers only what is valid now. */
export function ShortCard({ item }: { item: ShortItem }) {
  const run = useShortAction();
  const status = statusLabel(item.status);
  const items: MenuItem[] = menuActions(item).map(({ action, label }) => ({
    label,
    icon: ICONS[action],
    onSelect: () => run(item, action),
  }));
  const youtube = item.publish.platform === "youtube" && (item.status === "published" || item.status === "on_youtube" || item.status === "publishing");
  return (
    <li className="group/card @container relative min-w-0">
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
          <span className="absolute top-2 left-2">
            <StatusPill tone={status.tone} overlay>
              {status.label}
            </StatusPill>
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
            <span className="line-clamp-2">{contextLine(item)}</span>
          </span>
        </span>
      </Link>
      {/* Beside the title, just under the 9:16 frame (100cqw × 16/9 is the frame's height): next
          to the card link, not inside it, and always visible — no hover needed. */}
      <div className="absolute top-[calc(100cqw*16/9+0.375rem)] -right-1.5">
        <Menu label={`Actions for ${item.title}`} trigger={<MoreHorizontal aria-hidden="true" />} items={items} />
      </div>
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

