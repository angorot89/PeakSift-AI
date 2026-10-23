// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { clock, continueItems, momentLabel, nextAction, projectStage, relativeTime, shortLabel, type ProjectSummary } from "./workspace-rules.ts";

const P = "3f1c0a1e-0000-4000-8000-000000000001";
const CLIP = "3f1c0a1e-0000-4000-8000-000000000002";
const EDIT = "3f1c0a1e-0000-4000-8000-000000000003";

function project(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: P, name: "Bridge Lab", created_at: "2026-10-20T10:00:00Z", last_activity_at: "2026-10-22T10:00:00Z",
    source: null, transcript: null, detection: null,
    clips: { total: 0, ready: 0, working: 0, failed: 0, latest_ready_id: null },
    shorts: { total: 0, ready: 0, working: 0, failed: 0, recent: [] },
    plans: { ready: 0, latest_ready: null },
    published: { uploads: 0, working: 0, failed: 0, with_analytics: 0, last_synced_at: null },
    ...overrides,
  };
}
const ready = { id: "v", filename: "talk.mp4", status: "ready", duration_seconds: 3600 };
const transcribed = { source: ready, transcript: { status: "completed", progress_percent: 100 } };
const detected = (candidates: number, undecided = candidates) => ({
  ...transcribed,
  detection: { run_id: "r", status: "completed", candidates, undecided, saved: 0, dismissed: 0, top: [] },
});
const short = (status: string) => ({
  edit_id: EDIT, clip_id: CLIP, clip_title: "The joint", status, duration_seconds: 20,
  layout: "blur_background", captions_enabled: true, caption_style: "punch",
  created_at: "2026-10-22T09:00:00Z", updated_at: "2026-10-22T09:00:00Z",
});

describe("next best action", () => {
  const cases: [string, Partial<ProjectSummary>, string, string][] = [
    ["no source", {}, "upload", `/projects/${P}/source`],
    ["unreadable source", { source: { ...ready, status: "failed" } }, "source-failed", `/projects/${P}/source`],
    ["reading the file", { source: { ...ready, status: "processing_metadata" } }, "source-working", `/projects/${P}/source`],
    ["not transcribed", { source: ready }, "transcribe", `/projects/${P}/source`],
    ["transcribing", { source: ready, transcript: { status: "transcribing", progress_percent: 40 } }, "transcribing", `/projects/${P}/source`],
    ["transcript failed", { source: ready, transcript: { status: "failed", progress_percent: 10 } }, "transcript-failed", `/projects/${P}/source`],
    ["transcript ready", transcribed, "find-clips", `/projects/${P}/clips`],
    ["finding", { ...transcribed, detection: { ...detected(0).detection, status: "analyzing" } }, "finding", `/projects/${P}/clips`],
    ["nothing found", detected(0), "no-moments", `/projects/${P}/clips`],
    ["candidates", detected(3), "review-clips", `/projects/${P}/clips`],
    ["clip ready", { ...detected(3), clips: { total: 1, ready: 1, working: 0, failed: 0, latest_ready_id: CLIP } }, "create-short", `/projects/${P}/clips/${CLIP}/auto-edit`],
    ["plan ready", { ...detected(3), plans: { ready: 1, latest_ready: { plan_id: "x", clip_id: CLIP, recipe: "punchy" } } }, "plan-ready", `/projects/${P}/clips/${CLIP}/auto-edit`],
    ["rendering", { ...detected(3), shorts: { total: 1, ready: 0, working: 1, failed: 0, recent: [short("rendering")] } }, "rendering", `/projects/${P}/clips/${CLIP}`],
    ["short ready", { ...detected(3), shorts: { total: 1, ready: 1, working: 0, failed: 0, recent: [short("ready")] } }, "short-ready", `/projects/${P}/clips/${CLIP}?edit=${EDIT}`],
    ["upload failed", { ...detected(3), shorts: { total: 1, ready: 1, working: 0, failed: 0, recent: [short("ready")] }, published: { uploads: 0, working: 0, failed: 1, with_analytics: 0, last_synced_at: null } }, "upload-failed", `/projects/${P}/clips/${CLIP}?edit=${EDIT}`],
    ["uploading", { ...detected(3), shorts: { total: 1, ready: 1, working: 0, failed: 0, recent: [short("ready")] }, published: { uploads: 0, working: 1, failed: 0, with_analytics: 0, last_synced_at: null } }, "uploading", `/projects/${P}/clips/${CLIP}?edit=${EDIT}`],
    ["analytics without a job", { ...detected(3), shorts: { total: 1, ready: 1, working: 0, failed: 0, recent: [short("ready")] }, published: { uploads: 0, working: 0, failed: 1, with_analytics: 3, last_synced_at: null } }, "published", `/projects/${P}/analytics`],
    ["published", { ...detected(3), shorts: { total: 1, ready: 1, working: 0, failed: 0, recent: [short("ready")] }, published: { uploads: 1, working: 0, failed: 0, with_analytics: 0, last_synced_at: null } }, "published", `/projects/${P}/analytics`],
  ];
  for (const [name, state, key, href] of cases) {
    it(`${name} → ${key}`, () => {
      const action = nextAction(project(state));
      assert.equal(action.key, key);
      assert.equal(action.href, href);
    });
  }
  it("speaks plainly and asks nothing while PeakSift works", () => {
    const waiting = nextAction(project({ source: ready, transcript: { status: "transcribing", progress_percent: 1 } }));
    assert.equal(waiting.cta, undefined);
    assert.equal(nextAction(project(detected(1))).title, "1 clip ready to review");
    assert.equal(nextAction(project(detected(4, 2))).title, "2 clips ready to review");
    for (const [, state] of cases) {
      const text = Object.values(nextAction(project(state))).join(" ");
      assert.doesNotMatch(text, /celery|provider|candidate|fingerprint|embedding|null|undefined/i);
    }
  });
});

describe("workflow stage", () => {
  it("is the furthest stage reached", () => {
    assert.equal(projectStage(project()), 0);
    assert.equal(projectStage(project(transcribed)), 1);
    assert.equal(projectStage(project({ ...transcribed, clips: { total: 1, ready: 1, working: 0, failed: 0, latest_ready_id: CLIP } })), 2);
    assert.equal(projectStage(project({ published: { uploads: 1, working: 0, failed: 0, with_analytics: 0, last_synced_at: null } })), 3);
    assert.equal(projectStage(project({ published: { uploads: 1, working: 0, failed: 0, with_analytics: 2, last_synced_at: null } })), 4);
  });
});

describe("continue working", () => {
  it("puts problems first, then the most recent, one card per project", () => {
    const items = continueItems({
      project_count: 3,
      recent_shorts: [],
      projects: [
        project({ id: "a", name: "Calm", last_activity_at: "2026-10-22T12:00:00Z", ...detected(2) }),
        project({ id: "b", name: "Broken", last_activity_at: "2026-10-21T12:00:00Z", source: { ...ready, status: "failed" } }),
        project({ id: "c", name: "Older", last_activity_at: "2026-10-20T12:00:00Z", ...transcribed }),
      ],
    });
    assert.deepEqual(items.map((i) => i.projectName), ["Broken", "Calm", "Older"]);
    assert.equal(items[0].tone, "attention");
  });
});

describe("relative time", () => {
  const now = new Date("2026-10-22T12:00:00Z");
  it("reads naturally", () => {
    assert.equal(relativeTime("2026-10-22T11:59:30Z", now), "just now");
    assert.equal(relativeTime("2026-10-22T11:15:00Z", now), "45 min ago");
    assert.equal(relativeTime("2026-10-22T07:00:00Z", now), "5 h ago");
    assert.equal(relativeTime("2026-10-21T08:00:00Z", now), "yesterday");
    assert.equal(relativeTime("2026-10-18T12:00:00Z", now), "4 days ago");
    assert.equal(relativeTime("2026-09-01T12:00:00Z", now), "Sep 1");
  });
});

describe("moment labels and times", () => {
  it("names the ranking in creator words, grounded in rank and editorial score", () => {
    assert.equal(momentLabel(1, 40), "Top pick");
    assert.equal(momentLabel(2, 80), "Strong moment");
    assert.equal(momentLabel(3, 60), "Worth reviewing");
  });
  it("formats clip times like a player", () => {
    assert.equal(clock(112), "1:52");
    assert.equal(clock(9), "0:09");
    assert.equal(clock(3725), "1:02:05");
  });
});

describe("short labels", () => {
  it("tells versions of one clip apart in plain words", () => {
    assert.equal(shortLabel({ layout: "blur_background", captions_enabled: true, caption_style: "minimal" }), "Blur background · Minimal captions");
    assert.equal(shortLabel({ layout: "smart_reframe", captions_enabled: false, caption_style: null }), "Smart reframe · No captions");
    assert.equal(shortLabel({ layout: "new_layout", captions_enabled: true, caption_style: null }), "Vertical · Captions");
  });
});
