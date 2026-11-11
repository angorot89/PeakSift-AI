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
  primaryAction,
  publishingView,
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
    assert.deepEqual(filterCounts(items), { all: 5, drafts: 1, ready: 1, published: 1, attention: 1 });
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
    assert.deepEqual(labels(short()), ["Edit", "Download", "Publish", "Open project"]);
    assert.deepEqual(labels(published()), ["Edit", "Download", "View analytics", "Open project"]);
    assert.deepEqual(labels(short({ status: "rendering", preview: "clip" })), ["Edit", "Open project"]);
    assert.deepEqual(labels(short({ status: "draft", kind: "draft", edit_id: null, preview: "clip" })), ["Continue editing", "Open project"]);
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
