/**
 * Keeping background-job state correct in the browser when responses arrive out of order.
 *
 * Clips, edits, framing analyses and caption tracks are jobs with an `attempt` (a retry starts
 * a new one) and a status that only moves forward within an attempt. Status requests can
 * overlap with user actions (Render, Retry), so a response may describe an *older* state than
 * the one already shown — e.g. a poll issued before Retry returns "failed" after Retry returned
 * "queued". Accepting it would show the old failure and stop polling until a reload.
 *
 * The rules here are pure (no React, no timers of their own) so they are unit-tested directly.
 */

export type JobSnapshot = {
  id: string;
  attempt: number;
  status: string;
  progress_percent?: number;
};

/** Status order within one attempt: later stages win; terminal states share the last rank. */
export type StageRanks = Readonly<Record<string, number>>;

export function stageRanks(active: readonly string[], terminal: readonly string[]): StageRanks {
  const ranks: Record<string, number> = {};
  active.forEach((status, index) => (ranks[status] = index));
  terminal.forEach((status) => (ranks[status] = active.length));
  return ranks;
}

/** Whether `incoming` is at least as new as `current` (same job), so it may replace it. */
export function supersedes<T extends JobSnapshot>(current: T | null | undefined, incoming: T, ranks: StageRanks): boolean {
  if (!current || current.id !== incoming.id) return true;
  if (incoming.attempt !== current.attempt) return incoming.attempt > current.attempt;
  const a = ranks[current.status] ?? -1;
  const b = ranks[incoming.status] ?? -1;
  if (b !== a) return b > a;
  // Same stage: equal is accepted (staleness flags may change); progress never goes backwards.
  return (incoming.progress_percent ?? 0) >= (current.progress_percent ?? 0);
}

/** The newer of two snapshots of the same job (`current` when it is newer). */
export function newer<T extends JobSnapshot>(current: T | null | undefined, incoming: T, ranks: StageRanks): T {
  return current && !supersedes(current, incoming, ranks) ? current : incoming;
}

/**
 * Merge a freshly fetched list into the one on screen. Jobs are never deleted, so a job missing
 * from `incoming` was created after that request was issued and is kept; for jobs in both, the
 * newer snapshot wins. Sorted newest first by `created_at`.
 */
export function mergeJobs<T extends JobSnapshot & { created_at: string }>(
  current: readonly T[] | null | undefined,
  incoming: readonly T[],
  ranks: StageRanks,
): T[] {
  const byId = new Map<string, T>();
  for (const job of current ?? []) byId.set(job.id, job);
  for (const job of incoming) byId.set(job.id, newer(byId.get(job.id), job, ranks));
  return [...byId.values()].sort((x, y) => (x.created_at < y.created_at ? 1 : x.created_at > y.created_at ? -1 : 0));
}

export type Timers = {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
};

const browserTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/**
 * Poll with a quick first check, then at a steady interval. Calls are chained (the next one is
 * scheduled after the previous finished), so a slow request never overlaps the next one.
 * `tick` returns false to stop; a failing tick keeps polling. Returns a stop function.
 */
export function startPolling(
  tick: () => Promise<boolean>,
  { firstDelayMs, intervalMs, timers = browserTimers }: { firstDelayMs: number; intervalMs: number; timers?: Timers },
): () => void {
  let stopped = false;
  let handle: unknown = null;
  const schedule = (ms: number) => {
    handle = timers.set(() => void run(), ms);
  };
  const run = async () => {
    if (stopped) return;
    let again = true;
    try {
      again = await tick();
    } catch {
      again = true; // transient errors are reported by the caller; keep watching
    }
    if (!stopped && again) schedule(intervalMs);
  };
  schedule(firstDelayMs);
  return () => {
    stopped = true;
    if (handle !== null) timers.clear(handle);
  };
}
