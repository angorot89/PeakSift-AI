// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { activeGlobal, clipHref, projectHref, projectLocation } from "./navigation.ts";

const P = "3f1c0a1e-0000-4000-8000-000000000001";
const C = "3f1c0a1e-0000-4000-8000-000000000002";

describe("global navigation", () => {
  it("knows which destination a path belongs to", () => {
    assert.equal(activeGlobal("/home"), "home");
    assert.equal(activeGlobal("/projects"), "projects");
    assert.equal(activeGlobal(`/projects/${P}/clips/${C}`), "projects");
    assert.equal(activeGlobal("/analytics/abc"), "analytics");
    assert.equal(activeGlobal("/settings"), "settings");
    assert.equal(activeGlobal("/homework"), null);
  });
});

describe("project navigation", () => {
  it("builds section and clip links", () => {
    assert.equal(projectHref(P), `/projects/${P}`);
    assert.equal(projectHref(P, "clips"), `/projects/${P}/clips`);
    assert.equal(clipHref(P, C), `/projects/${P}/clips/${C}`);
  });
  it("finds the section and the clip of a path", () => {
    assert.deepEqual(projectLocation(`/projects/${P}`), { projectId: P, section: "overview", clipId: null });
    assert.deepEqual(projectLocation(`/projects/${P}/source`), { projectId: P, section: "source", clipId: null });
    assert.deepEqual(projectLocation(`/projects/${P}/clips/${C}/auto-edit`), { projectId: P, section: "clips", clipId: C });
    assert.deepEqual(projectLocation(`/projects/${P}/analytics`), { projectId: P, section: "analytics", clipId: null });
    assert.equal(projectLocation("/projects/new"), null);
    assert.equal(projectLocation("/projects"), null);
  });
});
