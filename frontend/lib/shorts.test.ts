// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  cardLabel,
  contextLine,
  continueHref,
  filterCounts,
  matchesSearch,
  menuActions,
  mergeQueue,
  nextFreeSlot,
  nextToReview,
  primaryAction,
  projectsOf,
  quickActions,
  performanceFreshness,
  performanceTotals,
  publishingView,
  relatedInsights,
  reviewQueue,
  reviewSummary,
  type ShortItem,
  type ShortStatus,
  statusDetail,
  statusLabel,
  visibleShorts,
} from "./shorts-rules.ts";

const NOW = new Date("2026-11-11T12:00:00Z");

function short(overrides: Partial<ShortItem> = {}): ShortItem {
  return {
    id: "e1",
    kind: "short",
    status: "ready",
    reason: null,
    title: "Why creators burn out",
    edit_id: "e1",
    clip_id: "c1",
    project: { id: "p1", name: "Podcast — Guest Interview" },
    source: { id: "v1", filename: "guest-interview.mp4" },
    duration_seconds: 42,
    preview: "short",
    version: { number: 1, count: 1 },
    template: null,
    brand: null,
    auto_edit: false,
    plan_ready: false,
    publish: { state: "not_published", platform: null, published_at: null, uploaded_at: null, privacy: null, simulated: false, video_url: null, job_id: null },
    performance: null,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-02T10:00:00Z",
    rendered_at: "2026-11-02T10:00:00Z",
    ...overrides,
  };
}

const published = (overrides: Partial<ShortItem> = {}) =>
  short({
    status: "published",
    publish: { ...short().publish, state: "published", platform: "youtube", published_at: "2026-10-18T09:00:00Z", uploaded_at: "2026-10-18T09:00:00Z", privacy: "public" },
    performance: { content_id: "pc1", views: 1320, likes: null, comments: null, observed_at: "2026-11-10T00:00:00Z", simulated: false, analytics_through: null },
    ...overrides,
  });

describe("status words", () => {
  it("names every status in the creator's words", () => {
    const all: ShortStatus[] = ["draft", "rendering", "ready", "publishing", "on_youtube", "published", "failed", "needs_attention"];
    assert.deepEqual(
      all.map((s) => statusLabel(s).label),
      ["Draft", "Rendering", "Ready", "Publishing", "On YouTube", "Published", "Failed", "Needs attention"],
    );
  });
  it("never calls an upload YouTube hasn't confirmed published", () => {
    const uploaded = short({ status: "on_youtube", publish: { ...short().publish, state: "on_youtube", uploaded_at: "2026-10-18T09:00:00Z" } });
    assert.equal(statusLabel(uploaded.status).label, "On YouTube");
    assert.equal(contextLine(uploaded, NOW), "YouTube · Uploaded Oct 18");
    assert.doesNotMatch(statusDetail(uploaded), /published/i);
  });
  it("explains a problem by its reason", () => {
    assert.match(statusDetail(short({ status: "failed", reason: "render_failed" })), /couldn't be rendered/);
    assert.match(statusDetail(short({ status: "needs_attention", reason: "publish_stalled" })), /resume/);
  });
  it("shows real publishing stages only", () => {
    const uploading = short({ status: "publishing", publish: { ...short().publish, state: "uploading" } });
    assert.equal(contextLine(uploading, NOW), "YouTube · Uploading…");
    assert.doesNotMatch(contextLine(uploading, NOW), /%/);
  });
  it("labels simulated publishing", () => {
    const fake = published({ publish: { ...published().publish, simulated: true } });
    assert.equal(contextLine(fake, NOW), "YouTube · Published Oct 18 (simulated)");
  });
});

describe("filters, search and sort", () => {
  const items = [
    short({ id: "a", status: "draft", kind: "draft", edit_id: null, version: null, preview: "clip", updated_at: "2026-11-05T00:00:00Z", created_at: "2026-11-05T00:00:00Z" }),
    short({ id: "b", title: "Lava jump", project: { id: "p2", name: "Speedrun Fails" }, updated_at: "2026-11-04T00:00:00Z", created_at: "2026-10-01T00:00:00Z" }),
    published({ id: "c", updated_at: "2026-11-03T00:00:00Z" }),
    short({ id: "d", status: "failed", reason: "render_failed", preview: "clip" }),
    short({ id: "e", status: "rendering", preview: "clip" }),
  ];
  it("counts each filter from the statuses (working Shorts only under All)", () => {
    assert.deepEqual(filterCounts(items), { all: 5, drafts: 1, ready: 1, scheduled: 0, published: 1, attention: 1, hidden: 0 });
  });
  it("keeps hidden Shorts under Hidden only, and scheduled ones under Scheduled", () => {
    const hidden = short({ id: "h", hidden: true });
    const scheduled = short({ id: "s", schedule: { at: "2026-11-13T19:00:00Z", platform: "tiktok" } });
    const mix = [short({ id: "r" }), hidden, scheduled, short({ id: "hs", hidden: true, schedule: scheduled.schedule })];
    assert.deepEqual(filterCounts(mix), { all: 2, drafts: 0, ready: 1, scheduled: 1, published: 0, attention: 0, hidden: 2 });
    assert.deepEqual(visibleShorts(mix, "all", "", "updated").map((i) => i.id).sort(), ["r", "s"]);
    assert.deepEqual(visibleShorts(mix, "hidden", "", "updated").map((i) => i.id).sort(), ["h", "hs"]);
    assert.deepEqual(visibleShorts(mix, "ready", "", "updated").map((i) => i.id), ["r"]);
    assert.deepEqual(visibleShorts(mix, "scheduled", "", "updated").map((i) => i.id), ["s"]);
  });
  it("filters by project and lists the projects by name", () => {
    const other = short({ id: "o", project: { id: "p2", name: "A Stream" } });
    assert.deepEqual(projectsOf([short(), other, short({ id: "x" })]), [
      { id: "p2", name: "A Stream" },
      { id: "p1", name: "Podcast — Guest Interview" },
    ]);
    assert.deepEqual(visibleShorts([short(), other], "all", "", "updated", "p2").map((i) => i.id), ["o"]);
  });
  it("says when and where a scheduled post goes out", () => {
    const line = contextLine(short({ schedule: { at: "2026-11-13T19:00:00Z", platform: "tiktok" } }), NOW);
    assert.match(line, /^TikTok · Scheduled Nov 1[34], \d{1,2}:00 (AM|PM)$/);
  });
  it("searches titles, projects and source names, ignoring case and accents", () => {
    assert.ok(matchesSearch(items[1], "LAVA"));
    assert.ok(matchesSearch(items[1], "speedrun jump"));
    assert.ok(matchesSearch(items[0], "guest-interview"));
    assert.ok(matchesSearch(short({ title: "Café talk" }), "cafe"));
    assert.ok(!matchesSearch(items[1], "podcast lava"));
  });
  it("sorts by activity, age or publication", () => {
    assert.deepEqual(visibleShorts(items, "all", "", "updated").map((i) => i.id).slice(0, 3), ["a", "b", "c"]);
    assert.equal(visibleShorts(items, "all", "", "oldest")[0].id, "b");
    assert.equal(visibleShorts(items, "all", "", "published")[0].id, "c");
    assert.deepEqual(visibleShorts(items, "attention", "", "updated").map((i) => i.id), ["d"]);
  });
});

describe("actions follow the state", () => {
  it("has one primary action per state", () => {
    assert.equal(primaryAction(short({ status: "draft", kind: "draft" }))?.label, "Continue editing");
    assert.equal(primaryAction(short())?.label, "Publish");
    assert.equal(primaryAction(published())?.label, "View performance");
    assert.equal(primaryAction(short({ status: "failed", reason: "render_failed" }))?.action, "fix_render");
    assert.equal(primaryAction(short({ status: "needs_attention", reason: "publish_failed" }))?.action, "fix_publish");
    assert.equal(primaryAction(short({ status: "rendering" })), null);
    assert.equal(primaryAction(short({ status: "publishing" })), null);
  });
  it("offers only valid menu actions", () => {
    const labels = (item: ShortItem) => menuActions(item).map((a) => a.label);
    assert.deepEqual(labels(short()), ["Edit", "Download", "Publish", "Open project", "Hide"]);
    assert.deepEqual(labels(published()), ["Edit", "Download", "View analytics", "Open project", "Hide"]);
    assert.deepEqual(labels(short({ status: "rendering", preview: "clip" })), ["Edit", "Open project", "Hide"]);
    assert.deepEqual(labels(short({ status: "draft", kind: "draft", edit_id: null, preview: "clip" })), ["Continue editing", "Open project", "Hide"]);
    assert.deepEqual(labels(short({ hidden: true })).at(-1), "Show in library");
  });
  it("puts the next step on the card itself", () => {
    const labels = (item: ShortItem) => quickActions(item).map((a) => a.label);
    assert.deepEqual(labels(short()), ["Publish", "Schedule", "Download"]);
    assert.deepEqual(labels(short({ schedule: { at: "2026-11-13T19:00:00Z", platform: "youtube" } })), ["Change time", "Download"]);
    assert.deepEqual(labels(published()), ["Analytics", "Download"]);
    assert.deepEqual(labels(short({ status: "draft", kind: "draft", edit_id: null, preview: "clip" })), ["Edit"]);
    assert.deepEqual(labels(short({ status: "rendering", preview: "clip" })), []);
    assert.deepEqual(labels(short({ hidden: true })), ["Show"]);
  });
  it("continues a draft where the work is", () => {
    const draft = short({ kind: "draft", status: "draft", edit_id: null });
    assert.equal(continueHref(draft), "/projects/p1/clips/c1/create");
    assert.equal(continueHref({ ...draft, plan_ready: true }), "/projects/p1/clips/c1/auto-edit");
    assert.equal(continueHref(short()), "/projects/p1/clips/c1?edit=e1");
  });
  it("names a card for assistive technology", () => {
    assert.equal(cardLabel(published()), "Why creators burn out, Published, 0:42, from Podcast — Guest Interview");
  });
});

describe("the publishing panel", () => {
  type Panel = Parameters<typeof publishingView>[1];
  type Job = NonNullable<Parameters<typeof publishingView>[2]>;
  const connected: Panel = {
    enabled: true,
    connection: { provider: "youtube", status: "connected", account_title: "", connected_at: "2026-11-01T00:00:00Z", analytics_access: false },
    edit_ready: true,
    defaults: { title: "t", description: "", tags: [], privacy: "private", made_for_kids: false },
    jobs: [],
  };
  const job = (overrides: Partial<Job>): Job => ({
    id: "j1", edit_id: "e1", provider: "youtube", status: "uploading", progress_percent: 40, bytes_uploaded: 4, bytes_total: 10,
    title: "Lava!", description: "", tags: [], privacy: "public", made_for_kids: false, video_url: null, studio_url: null,
    simulated: false, error_code: null, error_message: null, retryable: false, is_stale: false, awaiting_processing: false,
    attempt: 1, created_at: "2026-11-10T00:00:00Z", started_at: null, completed_at: null, published_at: null, ...overrides,
  });
  it("asks to connect before anything can be published", () => {
    const view = publishingView(short(), { ...connected, connection: null }, null);
    assert.equal(view.connection, "Not connected");
    assert.equal(view.action, "connect");
    assert.equal(publishingView(short(), { ...connected, connection: { ...connected.connection!, status: "needs_reconnect" } }, null).reconnect, true);
  });
  it("offers Publish only for a ready, unpublished Short", () => {
    assert.equal(publishingView(short(), connected, null).action, "publish");
    assert.equal(publishingView(short(), { ...connected, edit_ready: false }, null).action, null);
    assert.equal(publishingView(short(), { ...connected, enabled: false }, null).action, null);
  });
  it("follows a running upload in real stages, with nothing to click", () => {
    const view = publishingView(short({ status: "publishing" }), connected, job({}));
    assert.equal(view.stage, "Uploading…");
    assert.equal(view.action, null);
    assert.equal(publishingView(short(), connected, job({ is_stale: true })).state, "stalled");
  });
  it("retries a failed upload in place, or publishes again when it can't be resumed", () => {
    assert.equal(publishingView(short(), connected, job({ status: "failed", retryable: true })).action, null); // Retry is offered
    assert.equal(publishingView(short(), connected, job({ status: "failed", retryable: false })).action, "publish_again");
  });
  it("keeps a Short YouTube already has, whatever a later attempt did", () => {
    const onYouTube = published({ publish: { ...published().publish, job_id: "first" } });
    const view = publishingView(onYouTube, connected, job({ id: "later", status: "failed", retryable: true }));
    assert.equal(view.state, "published");
    assert.equal(view.publishedOn, "published");
    assert.equal(view.date, "2026-10-18T09:00:00Z");
  });
  it("never calls an upload published before YouTube says so", () => {
    const view = publishingView(short({ status: "on_youtube" }), connected, job({ status: "uploaded", completed_at: "2026-11-10T00:00:00Z" }));
    assert.equal(view.pill.label, "On YouTube");
    assert.equal(view.publishedOn, "uploaded");
  });
});

describe("the Short's performance", () => {
  const ready = { enabled: true, connected: true, connection_status: "connected", analytics_access: true, simulated: false };
  it("says why there are no figures, or how fresh they are", () => {
    assert.match(performanceFreshness({ ...ready, enabled: false }, null), /isn't available/);
    assert.match(performanceFreshness({ ...ready, analytics_access: false }, null), /Analytics not connected/);
    // History collected before stays, and says so.
    assert.equal(
      performanceFreshness({ ...ready, analytics_access: false }, { processed_through: "2026-11-09", counters_observed_at: null, daily: [] }),
      "Analytics not connected. Showing what was collected through Nov 9.",
    );
    assert.match(performanceFreshness({ ...ready, connection_status: "needs_reconnect" }, null), /paused: reconnect YouTube/);
    assert.match(performanceFreshness(ready, { processed_through: null, counters_observed_at: null, daily: [] }), /Waiting for YouTube data/);
    assert.match(performanceFreshness(ready, { processed_through: "2026-10-20", counters_observed_at: null, daily: [] }), /^Updated through Oct 20/);
  });
  it("adds up only what YouTube reported", () => {
    const day = (date: string, w: number | null, s: number | null) => ({ date, watch_time_seconds: w, subscribers_gained: s });
    const none = performanceTotals({ processed_through: null, counters_observed_at: null, daily: [day("2026-10-01", null, null)] });
    assert.equal(none.watchTime, "—");
    assert.equal(none.subscribers, "—");
    const days = Array.from({ length: 9 }, (_, i) => day(`2026-10-${String(i + 1).padStart(2, "0")}`, 600, i === 0 ? null : 1));
    const totals = performanceTotals({ processed_through: "2026-10-09", counters_observed_at: null, daily: days });
    assert.equal(totals.watchTime, "1 h 30 min");
    assert.equal(totals.subscribers, "8");
    assert.equal(totals.firstWeek.size, 7);
    assert.ok(totals.firstWeek.has("2026-10-07") && !totals.firstWeek.has("2026-10-08"));
  });
  it("shows only observed patterns that include this Short", () => {
    const insight = (id: string, group: string[], dismissed = false) => ({ id, statement: id, dismissed, group: group.map((g) => ({ id: g })), comparison: [] });
    const found = relatedInsights({ insights: [insight("a", ["c1", "c2"]), insight("b", ["c3"]), insight("c", ["c1"], true)] }, "c1");
    assert.deepEqual(found.map((i) => i.id), ["a"]);
  });
});

describe("state matrix: no contradictory status or action", () => {
  const states: [ShortStatus, ShortItem["reason"], ShortItem["preview"], ShortItem["kind"]][] = [
    ["draft", null, "clip", "draft"],
    ["rendering", null, "clip", "short"],
    ["rendering", null, null, "draft"],
    ["failed", "render_failed", "clip", "short"],
    ["failed", "clip_failed", null, "draft"],
    ["needs_attention", "render_stalled", "clip", "short"],
    ["ready", null, "short", "short"],
    ["publishing", null, "short", "short"],
    ["needs_attention", "publish_failed", "short", "short"],
    ["needs_attention", "publish_stalled", "short", "short"],
    ["on_youtube", null, "short", "short"],
    ["published", null, "short", "short"],
  ];
  for (const [status, reason, preview, kind] of states) {
    it(`${status}${reason ? ` (${reason})` : ""}, ${kind}`, () => {
      const item = short({ status, reason, preview, kind, edit_id: kind === "draft" ? null : "e1" });
      const primary = primaryAction(item);
      const menu = menuActions(item).map((a) => a.action);
      // Publish only for a rendered Short not yet on YouTube.
      if (primary?.action === "publish" || menu.includes("publish")) assert.equal(status, "ready");
      // Download only when there is a rendered file.
      if (menu.includes("download")) assert.equal(preview, "short");
      // Performance only once it is on YouTube.
      if (primary?.action === "performance") assert.ok(status === "published" || status === "on_youtube");
      // Working states wait (no primary action); problems always have one.
      if (status === "rendering" || status === "publishing") assert.equal(primary, null);
      if (status === "failed" || status === "needs_attention") assert.ok(primary?.label === "Fix issue");
      // A draft is never "edited" as a version, and every state can open its project.
      if (kind === "draft") assert.ok(!menu.includes("edit"));
      assert.ok(menu.includes("project"));
      // The words never claim more than the state.
      assert.ok(!(status !== "published" && /^Published/.test(statusLabel(status).label)));
    });
  }
});

describe("the review queue", () => {
  it("holds exactly what the Ready tab holds, newest render first", () => {
    const items = [
      short({ id: "old", rendered_at: "2026-11-01T10:00:00Z" }),
      short({ id: "new", rendered_at: "2026-11-05T10:00:00Z" }),
      short({ id: "hidden", hidden: true }),
      short({ id: "planned", schedule: { at: "2026-11-20T18:00:00Z", platform: "youtube" } }),
      short({ id: "draft", kind: "draft", status: "draft", edit_id: null, preview: "clip" }),
      published({ id: "out" }),
    ];
    assert.deepEqual(reviewQueue(items).map((item) => item.id), ["new", "old"]);
    assert.deepEqual(
      reviewQueue(items).map((item) => item.id).sort(),
      visibleShorts(items, "ready", "", "updated").map((item) => item.id).sort(),
    );
  });

  it("offers the next posting time nobody has taken, never one in the past", () => {
    const upcoming = ["2026-11-11T11:00:00Z", "2026-11-11T19:00:00Z", "2026-11-12T19:00:00Z"];
    assert.equal(nextFreeSlot(upcoming, [], NOW), "2026-11-11T19:00:00Z");
    assert.equal(nextFreeSlot(upcoming, ["2026-11-11T19:00:00.000Z"], NOW), "2026-11-12T19:00:00Z");
    assert.equal(nextFreeSlot(upcoming, ["2026-11-11T19:00:00Z", "2026-11-12T19:00:00Z"], NOW), null);
    assert.equal(nextFreeSlot([], [], NOW), null);
  });

  it("moves on to the next Short not yet handled, wrapping, and stops at the end", () => {
    const queue = [short({ id: "a" }), short({ id: "b" }), short({ id: "c" })];
    assert.equal(nextToReview(queue, 0, {}), 1);
    assert.equal(nextToReview(queue, 0, { b: "skipped" }), 2);
    assert.equal(nextToReview(queue, 2, { a: "published" }), 1);
    assert.equal(nextToReview(queue, 1, { a: "scheduled", b: "scheduled", c: "skipped" }), null);
  });

  it("keeps its order during a review and adds Shorts that became ready", () => {
    const a = short({ id: "a" });
    const b = short({ id: "b" });
    const c = short({ id: "c" });
    assert.deepEqual(mergeQueue(null, [a, b], false).map((item) => item.id), ["a", "b"]);
    assert.deepEqual(mergeQueue([a, b], [c], false).map((item) => item.id), ["c"]);
    assert.deepEqual(mergeQueue([a, b], [b, c], true).map((item) => item.id), ["a", "b", "c"]);
    const same = [a, b];
    assert.equal(mergeQueue(same, [b], true), same);
  });

  it("sums up the review in plain words", () => {
    assert.equal(reviewSummary({}), "Nothing posted yet");
    assert.equal(reviewSummary({ a: "skipped", b: "scheduled", c: "scheduled", d: "published" }), "2 scheduled, 1 published, 1 skipped");
  });
});
