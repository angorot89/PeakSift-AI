// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
// The next best action itself is decided by the server (backend/tests/test_next_action.py).
import {
  clock,
  continueVisual,
  displayName,
  gettingStarted,
  momentLabel,
  projectStage,
  relativeTime,
  shortLabel,
  workflowSteps,
  type Home,
  type ProjectSummary,
} from "./workspace-rules.ts";

const P = "3f1c0a1e-0000-4000-8000-000000000001";
const CLIP = "3f1c0a1e-0000-4000-8000-000000000002";

function project(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: P, name: "Bridge Lab", created_at: "2026-10-20T10:00:00Z", last_activity_at: "2026-10-22T10:00:00Z",
    source: null, transcript: null, detection: null,
    clips: { total: 0, ready: 0, working: 0, failed: 0, latest_ready_id: null },
    shorts: { total: 0, ready: 0, working: 0, failed: 0, recent: [] },
    plans: { ready: 0, latest_ready: null },
    published: { uploads: 0, working: 0, failed: 0, with_analytics: 0, last_synced_at: null },
    next_action: { key: "upload", title: "Add your long video", description: "", cta: "Upload a video", href: "/", tone: "action" },
    ...overrides,
  };
}
const ready = { id: "v", filename: "talk.mp4", status: "ready", duration_seconds: 3600 };
const transcribed = { source: ready, transcript: { status: "completed", progress_percent: 100 } };
const detected = (candidates: number, undecided = candidates) => ({
  ...transcribed,
  detection: { run_id: "r", status: "completed", candidates, undecided, saved: 0, dismissed: 0, top: [] },
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

describe("getting started", () => {
  it("follows real progress and completes with the first ready Short", () => {
    const home = (p: ProjectSummary): Home => ({ projects: [p], project_count: 1, recent_shorts: [], continue_items: [] });
    assert.deepEqual(gettingStarted(home(project())).steps.map((s) => s.done), [false, false, false]);
    assert.deepEqual(gettingStarted(home(project({ source: ready }))).steps.map((s) => s.done), [true, false, false]);
    const found = home(project(detected(3)));
    assert.deepEqual(gettingStarted(found).steps.map((s) => s.done), [true, true, false]);
    assert.equal(gettingStarted(found).complete, false);
    const made = project({ ...detected(3), shorts: { total: 1, ready: 1, working: 0, failed: 0, recent: [] } });
    assert.equal(gettingStarted(home(made)).complete, true);
  });
});

describe("workflow steps", () => {
  const states = (p: ProjectSummary) => workflowSteps(p).map((step) => step.state);
  it("starts at Upload for an empty project", () => {
    assert.deepEqual(states(project()), ["current", "upcoming", "upcoming", "upcoming", "upcoming"]);
  });
  it("follows real progress and says when PeakSift is working", () => {
    assert.deepEqual(states(project({ source: ready })), ["done", "current", "upcoming", "upcoming", "upcoming"]);
    assert.deepEqual(states(project({ source: ready, transcript: { status: "transcribing", progress_percent: 40 } })), [
      "done", "working", "upcoming", "upcoming", "upcoming",
    ]);
    assert.deepEqual(states(project(detected(4))), ["done", "done", "done", "current", "upcoming"]);
    assert.equal(workflowSteps(project(detected(4)))[2].detail, "4 moments");
  });
  it("flags problems instead of hiding them", () => {
    assert.equal(workflowSteps(project(detected(0)))[2].state, "attention");
    assert.equal(workflowSteps(project({ source: { ...ready, status: "failed" } }))[0].state, "attention");
  });
  it("finishes once a Short is on YouTube", () => {
    const shorts = { total: 1, ready: 1, working: 0, failed: 0, recent: [] };
    const published = { uploads: 1, working: 0, failed: 0, with_analytics: 0, last_synced_at: null };
    assert.deepEqual(states(project({ ...detected(3), shorts })), ["done", "done", "done", "done", "current"]);
    assert.deepEqual(states(project({ ...detected(3), shorts, published })), ["done", "done", "done", "done", "done"]);
  });
});

describe("home helpers", () => {
  it("makes a friendly name from the email", () => {
    assert.equal(displayName("amine@example.com"), "Amine");
    assert.equal(displayName(""), "");
  });
  it("shows the moments waiting, the Short in question, or the source", () => {
    const moment = { id: "m", rank: 1, title: "A", start_time: 10, end_time: 30, duration_seconds: 20, category: "insight", overall_score: 80 };
    const withMoments = project({ ...detected(5), detection: { ...detected(5).detection, top: [moment] } });
    assert.deepEqual(continueVisual("review-clips", withMoments), { kind: "moments", moments: [moment], count: 5 });
    assert.equal(continueVisual("transcribe", project({ source: ready })).kind, "source");
    assert.equal(continueVisual("upload", project()).kind, "none");
    assert.equal(continueVisual("short-ready", project({ source: ready })).kind, "source"); // no Short listed: the source
  });
});
