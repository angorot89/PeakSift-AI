// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mergeJobs, newer, stageRanks, startPolling, supersedes, type Timers } from "./status-sync.ts";

const RANKS = stageRanks(["queued", "rendering", "validating"], ["ready", "failed"]);

type Job = { id: string; attempt: number; status: string; progress_percent: number; created_at: string };
const job = (status: string, attempt = 1, progress = 0, id = "a", created_at = "2026-01-01T00:00:00Z"): Job => ({
  id,
  attempt,
  status,
  progress_percent: progress,
  created_at,
});

/** Manual clock: timers fire only when the test advances time. */
function fakeTimers() {
  let now = 0;
  let next = 1;
  const pending = new Map<number, { at: number; fn: () => void }>();
  const timers: Timers = {
    set: (fn, ms) => {
      const id = next++;
      pending.set(id, { at: now + ms, fn });
      return id;
    },
    clear: (handle) => void pending.delete(handle as number),
  };
  async function advance(ms: number) {
    const until = now + ms;
    for (;;) {
      const due = [...pending.entries()].filter(([, t]) => t.at <= until).sort((x, y) => x[1].at - y[1].at)[0];
      if (!due) break;
      pending.delete(due[0]);
      now = due[1].at;
      due[1].fn();
      await new Promise((resolve) => setImmediate(resolve)); // let the tick's promise settle
      await new Promise((resolve) => setImmediate(resolve));
    }
    now = until;
  }
  return { timers, advance, pending: () => pending.size };
}

describe("supersedes / newer", () => {
  it("accepts later stages and more progress within an attempt", () => {
    assert.equal(supersedes(job("queued"), job("rendering"), RANKS), true);
    assert.equal(supersedes(job("rendering", 1, 40), job("rendering", 1, 80), RANKS), true);
    assert.equal(supersedes(job("rendering"), job("ready"), RANKS), true);
  });

  it("rejects responses older than the state on screen", () => {
    assert.equal(supersedes(job("ready"), job("rendering"), RANKS), false);
    assert.equal(supersedes(job("rendering", 1, 80), job("rendering", 1, 40), RANKS), false);
    // A poll that started before Retry returns attempt 1's failure after attempt 2 was queued.
    assert.equal(supersedes(job("queued", 2), job("failed", 1), RANKS), false);
    assert.deepEqual(newer(job("queued", 2), job("failed", 1), RANKS), job("queued", 2));
  });

  it("a retry (newer attempt) replaces a terminal state", () => {
    assert.equal(supersedes(job("failed", 1), job("queued", 2), RANKS), true);
  });

  it("another job, or no current state, is always accepted", () => {
    assert.equal(supersedes(null, job("queued"), RANKS), true);
    assert.equal(supersedes(job("ready", 3, 100, "a"), job("queued", 1, 0, "b"), RANKS), true);
  });
});

describe("mergeJobs", () => {
  it("keeps a job created after the list request was issued", () => {
    const onScreen = [job("queued", 1, 0, "new", "2026-01-02T00:00:00Z"), job("rendering", 1, 50, "old")];
    const staleList = [job("rendering", 1, 50, "old")];
    const merged = mergeJobs(onScreen, staleList, RANKS);
    assert.deepEqual(
      merged.map((j) => j.id),
      ["new", "old"],
    );
  });

  it("never regresses a job and takes newer snapshots", () => {
    const onScreen = [job("ready", 1, 100, "x"), job("queued", 1, 0, "y")];
    const list = [job("rendering", 1, 50, "x"), job("rendering", 1, 50, "y")];
    const merged = mergeJobs(onScreen, list, RANKS);
    assert.equal(merged.find((j) => j.id === "x")?.status, "ready");
    assert.equal(merged.find((j) => j.id === "y")?.status, "rendering");
  });

  it("orders newest first", () => {
    const merged = mergeJobs(null, [job("ready", 1, 100, "a", "2026-01-01T00:00:00Z"), job("ready", 1, 100, "b", "2026-01-03T00:00:00Z")], RANKS);
    assert.deepEqual(
      merged.map((j) => j.id),
      ["b", "a"],
    );
  });
});

describe("startPolling", () => {
  it("fast completion: the API answers active, the worker finishes at once, the first check shows ready", async () => {
    // The POST returned "queued"; by the time anything polls, the worker has finished.
    const server = job("ready", 1, 100);
    let shown: Job = job("queued");
    const clock = fakeTimers();
    let calls = 0;
    const stop = startPolling(
      async () => {
        calls += 1;
        shown = newer(shown, server, RANKS);
        return RANKS[shown.status] < RANKS.ready; // keep polling only while active
      },
      { firstDelayMs: 1000, intervalMs: 4000, timers: clock.timers },
    );
    await clock.advance(999);
    assert.equal(calls, 0);
    await clock.advance(1);
    assert.equal(calls, 1);
    assert.equal(shown.status, "ready"); // no reload, no waiting for a 4 s interval
    assert.equal(clock.pending(), 0); // and polling stopped
    stop();
  });

  it("a stale in-flight response cannot undo a retry, and polling continues", async () => {
    let shown: Job = job("failed", 1);
    shown = newer(shown, job("queued", 2), RANKS); // Retry's response
    const responses = [job("failed", 1), job("rendering", 2, 40), job("ready", 2, 100)];
    const clock = fakeTimers();
    startPolling(
      async () => {
        shown = newer(shown, responses.shift()!, RANKS);
        return RANKS[shown.status] < RANKS.ready;
      },
      { firstDelayMs: 1000, intervalMs: 4000, timers: clock.timers },
    );
    await clock.advance(1000);
    assert.deepEqual([shown.attempt, shown.status], [2, "queued"]); // the stale failure was ignored
    await clock.advance(4000);
    assert.equal(shown.status, "rendering");
    await clock.advance(4000);
    assert.deepEqual([shown.attempt, shown.status], [2, "ready"]);
    assert.equal(clock.pending(), 0);
  });

  it("errors keep polling; requests never overlap; stop cancels", async () => {
    const clock = fakeTimers();
    let calls = 0;
    let release: () => void = () => {};
    const stop = startPolling(
      async () => {
        calls += 1;
        if (calls === 1) throw new Error("network");
        if (calls === 2) await new Promise<void>((resolve) => (release = resolve)); // a slow request
        return true;
      },
      { firstDelayMs: 1000, intervalMs: 4000, timers: clock.timers },
    );
    await clock.advance(1000); // fails
    await clock.advance(4000); // slow call in flight
    assert.equal(calls, 2);
    await clock.advance(20000);
    assert.equal(calls, 2); // nothing scheduled while the slow request is pending
    release();
    await new Promise((resolve) => setImmediate(resolve));
    await clock.advance(4000);
    assert.equal(calls, 3);
    stop();
    await clock.advance(20000);
    assert.equal(calls, 3);
    assert.equal(clock.pending(), 0);
  });
});
