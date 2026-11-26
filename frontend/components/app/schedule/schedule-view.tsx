"use client";

import { CalendarClock, ChevronLeft, ChevronRight, Clock, Smartphone } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { PublishBody } from "@/components/app/editor/publish-dialog";
import { PageHeader } from "@/components/app/page-header";
import { PostingTimes } from "@/components/app/schedule/posting-times";
import { ScheduledPost, formatWhen } from "@/components/app/schedule/scheduled-post";
import { ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { Dialog } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { VideoFrame } from "@/components/ui/video-frame";
import { editContentUrl } from "@/lib/edits";
import { getCalendar, getPostingSlots, type CalendarItem, type PostingSlots, type PublishCalendar } from "@/lib/publishing";
import {
  addDays,
  dayKey,
  groupByDay,
  isSameDay,
  postState,
  slotsSummary,
  toLocalInput,
  weekDays,
  weekLabel,
  weekStart,
  type PostTone,
} from "@/lib/schedule-rules";
import { getShorts, shortHref, type ShortItem } from "@/lib/shorts";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

const TONE: Record<PostTone, StatusTone> = {
  scheduled: "accent",
  working: "processing",
  done: "success",
  attention: "warning",
};
const UPCOMING_DAYS = 60; // how far ahead "already scheduled" is known for the ready list
const WORKING = ["queued", "preparing", "uploading"];

type Loaded = { week: PublishCalendar; upcoming: CalendarItem[]; shorts: ShortItem[]; posting: PostingSlots };

const clockTime = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

function Post({ item, onChanged }: { item: CalendarItem; onChanged: () => void }) {
  const [managing, setManaging] = useState(false);
  const state = postState(item.job);
  const scheduled = item.job.status === "scheduled";
  return (
    <li className="rounded-control border border-border bg-surface-2/70 p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <time dateTime={item.at} className="tabular text-small font-medium text-foreground">
          {clockTime(item.at)}
        </time>
        <StatusPill tone={TONE[state.tone]}>{state.label}</StatusPill>
      </div>
      <Link
        href={shortHref(item.job.edit_id)}
        dir="auto"
        className="mt-1.5 line-clamp-2 block text-sm font-medium break-words text-foreground underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {item.job.title}
      </Link>
      <p className="mt-0.5 truncate text-caption text-subtle">{item.project_name}</p>
      {item.job.status === "failed" && item.job.error_message ? (
        <p className="mt-1.5 text-caption text-pretty text-amber-200">{item.job.error_message}</p>
      ) : null}
      {scheduled ? (
        <div className="mt-2">
          {managing ? (
            <ScheduledPost
              compact
              job={item.job}
              onChange={() => {
                setManaging(false);
                onChanged();
              }}
              onCancelled={onChanged}
            />
          ) : (
            <button
              type="button"
              onClick={() => setManaging(true)}
              className="min-h-8 rounded text-caption text-accent-soft underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:min-h-11"
            >
              Change, publish now or cancel
            </button>
          )}
        </div>
      ) : null}
    </li>
  );
}

function ReadyShort({
  short,
  slot,
  onSchedule,
}: {
  short: ShortItem;
  /** This Short's next free posting slot, when the creator has posting times. */
  slot?: Date;
  onSchedule: (when?: string) => void;
}) {
  return (
    <li className="flex flex-col gap-3 rounded-block border border-border bg-surface p-3">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {short.edit_id ? (
          <VideoFrame src={editContentUrl(short.edit_id)} ratio="vertical" icon={Smartphone} className="w-12 shrink-0 rounded-control border border-border" />
        ) : null}
        <div className="min-w-0 flex-1">
          <Link
            href={shortHref(short.id)}
            dir="auto"
            className="line-clamp-2 text-sm font-medium break-words text-foreground underline-offset-2 hover:underline"
          >
            {short.title}
          </Link>
          <p className="truncate text-caption text-subtle">{short.project.name}</p>
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {slot ? (
          <Button size="sm" onClick={() => onSchedule(toLocalInput(slot))}>
            <CalendarClock aria-hidden="true" />
            {formatWhen(slot)}
          </Button>
        ) : null}
        <Button variant="secondary" size="sm" onClick={() => onSchedule()}>
          {slot ? "Other time" : (
            <>
              <CalendarClock aria-hidden="true" />
              Schedule
            </>
          )}
        </Button>
      </div>
    </li>
  );
}

/**
 * Schedule & Post: the week's posts at the times they go out, in the creator's local time, and
 * the ready Shorts that have no time yet. Scheduling uses the same reviewed-metadata dialog as
 * publishing; nothing is uploaded before its time.
 */
export function ScheduleView() {
  const [start, setStart] = useState(() => weekStart(new Date()));
  // The Short being scheduled, and the time offered for it (its next free posting slot, if any).
  const [scheduling, setScheduling] = useState<{ short: ShortItem; when?: string } | null>(null);
  const [editingTimes, setEditingTimes] = useState(false);

  const load = useCallback(async (): Promise<Loaded> => {
    const now = new Date();
    const [week, ahead, library, posting] = await Promise.all([
      getCalendar(start, addDays(start, 7)),
      getCalendar(now, addDays(now, UPCOMING_DAYS)),
      getShorts(),
      getPostingSlots(),
    ]);
    return { week, upcoming: ahead.items, shorts: library.shorts, posting };
  }, [start]);
  const { data, error, reload } = useApi(load);
  const week = data?.week ?? null;
  // Follow a post while it uploads, so the calendar turns from "Publishing" to "On YouTube".
  const working = Boolean(week?.items.some((item) => WORKING.includes(item.job.status)));
  usePolling(working, async () => reload(), dayKey(start));

  const days = useMemo(() => weekDays(start), [start]);
  const byDay = useMemo(() => groupByDay(week?.items ?? []), [week]);
  const waiting = useMemo(
    () => new Set((data?.upcoming ?? []).filter((item) => item.job.status === "scheduled").map((item) => item.job.edit_id)),
    [data],
  );
  const ready = (data?.shorts ?? []).filter(
    (short) => short.kind === "short" && short.status === "ready" && short.edit_id && !waiting.has(short.edit_id),
  );
  const today = new Date();
  const thisWeek = isSameDay(start, weekStart(today));
  const posting = data?.posting ?? null;
  // Free posting slots: the ones in this week show on the calendar; ready Shorts get one each.
  const freeSlots = useMemo(() => (posting?.upcoming ?? []).map((iso) => new Date(iso)), [posting]);
  const freeByDay = useMemo(() => groupByDay(freeSlots.map((slot) => ({ at: slot.toISOString() }))), [freeSlots]);

  return (
    <div className="space-y-10">
      <PageHeader
        title="Schedule"
        description="What goes out, and when. Times are in your local time; nothing is uploaded before its time."
        action={
          <Button variant="secondary" onClick={() => setEditingTimes(true)} disabled={!posting}>
            <Clock aria-hidden="true" />
            Posting times
          </Button>
        }
      />

      {error && !week ? <ErrorState title="Your schedule could not be loaded" message={error} onRetry={reload} /> : null}

      {week && !week.connection_ready ? (
        <InlineAlert
          tone="info"
          title="Connect YouTube to schedule posts"
          action={<ButtonLink href="/settings#youtube">Open Settings</ButtonLink>}
        >
          Scheduled posts go to your connected channel. Connect it once, then pick a time for any ready Short.
        </InlineAlert>
      ) : null}

      <section aria-labelledby="week-heading">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 id="week-heading" className="text-section">
            <time dateTime={dayKey(start)}>{weekLabel(start)}</time>
          </h2>
          <div className="flex items-center gap-1.5">
            <IconButton aria-label="Previous week" onClick={() => setStart((value) => addDays(value, -7))}>
              <ChevronLeft aria-hidden="true" />
            </IconButton>
            <Button variant="secondary" size="sm" disabled={thisWeek} onClick={() => setStart(weekStart(new Date()))}>
              This week
            </Button>
            <IconButton aria-label="Next week" onClick={() => setStart((value) => addDays(value, 7))}>
              <ChevronRight aria-hidden="true" />
            </IconButton>
          </div>
        </div>

        {!week && !error ? (
          <div role="status" aria-label="Loading your schedule" className="grid gap-3 2xl:grid-cols-7">
            {days.map((day) => (
              <Skeleton key={dayKey(day)} className="h-12 rounded-block 2xl:h-56" />
            ))}
          </div>
        ) : null}

        {week ? (
          // Seven columns only where each is wide enough to read; otherwise one row per day.
          <ol className="grid gap-3 2xl:grid-cols-7">
            {days.map((day) => {
              const key = dayKey(day);
              const posts = byDay.get(key) ?? [];
              const free = freeByDay.get(key) ?? [];
              const isToday = isSameDay(day, today);
              return (
                <li
                  key={key}
                  aria-current={isToday ? "date" : undefined}
                  className={`flex min-w-0 flex-col gap-2 rounded-block border p-2.5 sm:flex-row sm:items-start 2xl:min-h-56 2xl:flex-col 2xl:items-stretch ${
                    isToday ? "border-accent/50 bg-accent/[0.05]" : "border-border bg-surface/60"
                  }`}
                >
                  <h3 className="flex shrink-0 items-baseline justify-between gap-2 px-0.5 text-small font-medium sm:w-28 sm:flex-col sm:justify-start sm:gap-0.5 2xl:w-auto 2xl:flex-row 2xl:justify-between">
                    <time dateTime={key} className={isToday ? "text-accent-soft" : "text-foreground"}>
                      {day.toLocaleDateString(undefined, { weekday: "short" })} {day.getDate()}
                    </time>
                    {isToday ? <span className="text-caption text-accent-soft">Today</span> : null}
                  </h3>
                  {posts.length || free.length ? (
                    <ul className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-1">
                      {posts.map((item) => (
                        <Post key={item.job.id} item={item} onChanged={reload} />
                      ))}
                      {free.map((slot) => (
                        // A posting time with no post yet: an invitation, not a commitment.
                        <li
                          key={slot.at}
                          className="flex min-h-11 items-center justify-between gap-2 rounded-control border border-dashed border-border-strong px-2.5 py-1.5"
                        >
                          <time dateTime={slot.at} className="tabular text-small text-muted">
                            {clockTime(slot.at)}
                          </time>
                          <span className="text-caption text-subtle">Free slot</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="px-0.5 text-caption text-subtle sm:pt-0.5">Nothing planned</p>
                  )}
                </li>
              );
            })}
          </ol>
        ) : null}
      </section>

      {week ? (
        <section aria-labelledby="ready-heading">
          <SectionHeader
            id="ready-heading"
            title="Ready to schedule"
            description={
              ready.length
                ? posting?.slots.length
                  ? `Finished Shorts with no post planned. Your rhythm: ${slotsSummary(posting.slots)}.`
                  : "Finished Shorts with no post planned. Pick a time, or set your posting times once and take the next free one."
                : "Every ready Short already has a post planned, or nothing is ready yet."
            }
          />
          {ready.length ? (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {ready.map((short, index) => (
                // Each ready Short is offered its own free posting slot, in order.
                <ReadyShort
                  key={short.id}
                  short={short}
                  slot={freeSlots[index]}
                  onSchedule={(when) => setScheduling({ short, when })}
                />
              ))}
            </ul>
          ) : (
            <ButtonLink href="/shorts" variant="secondary">
              Open your Shorts
            </ButtonLink>
          )}
        </section>
      ) : null}

      <Dialog
        open={scheduling !== null}
        onClose={() => {
          setScheduling(null);
          reload();
        }}
        title="Publish"
        description={scheduling?.short.title}
      >
        {scheduling?.short.edit_id ? (
          <PublishBody
            editId={scheduling.short.edit_id}
            durationSeconds={scheduling.short.duration_seconds}
            returnTo="/schedule"
            initialWhen={scheduling.when}
            onClose={() => {
              setScheduling(null);
              reload();
            }}
          />
        ) : null}
      </Dialog>

      <Dialog
        open={editingTimes}
        onClose={() => setEditingTimes(false)}
        title="Posting times"
        description="The times you like to post at each week."
      >
        {editingTimes && posting ? (
          <PostingTimes current={posting} onSaved={reload} onClose={() => setEditingTimes(false)} />
        ) : null}
      </Dialog>
    </div>
  );
}
