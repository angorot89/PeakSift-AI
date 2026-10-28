import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { copilotScope, lengthNote, starters, threadKey, waitingText } from "./copilot-rules.ts";

const P = "3f1c0a1e-0000-4000-8000-000000000001";
const C = "3f1c0a1e-0000-4000-8000-000000000002";
const E = "3f1c0a1e-0000-4000-8000-000000000003";

describe("copilot scope", () => {
  it("knows the page and its objects from the address", () => {
    assert.deepEqual(copilotScope(`/projects/${P}`), { page: "overview", projectId: P, clipId: null, editId: null });
    assert.equal(copilotScope(`/projects/${P}/clips`).page, "moments");
    assert.equal(copilotScope(`/projects/${P}/assets`).page, "assets");
    assert.equal(copilotScope(`/projects/${P}/analytics`).page, "project_analytics");
    assert.deepEqual(copilotScope(`/projects/${P}/clips/${C}`, `?edit=${E}&tool=captions`), {
      page: "editor", projectId: P, clipId: C, editId: E,
    });
    assert.equal(copilotScope(`/projects/${P}/clips/${C}/create`).page, "create");
    assert.equal(copilotScope(`/projects/${P}/clips/${C}/auto-edit`, `?edit=${E}`).editId, null);
    assert.equal(copilotScope("/projects/new").page, "new_project");
    assert.equal(copilotScope("/projects").page, "projects");
    assert.equal(copilotScope(`/analytics/${P}`).page, "short_analytics");
    assert.equal(copilotScope("/analytics").page, "analytics");
    assert.equal(copilotScope("/settings").page, "settings");
    assert.equal(copilotScope("/home").page, "home");
    assert.equal(copilotScope("/projects/not-an-id").page, "projects");
  });

  it("keeps one conversation per project and one for the workspace", () => {
    assert.equal(threadKey(copilotScope(`/projects/${P}/clips/${C}`)), P);
    assert.equal(threadKey(copilotScope(`/projects/${P}`)), P);
    assert.equal(threadKey(copilotScope("/analytics")), "workspace");
  });
});

describe("copilot wording", () => {
  it("suggests questions that fit the page", () => {
    assert.ok(starters("overview").includes("What should I do next?"));
    assert.ok(starters("moments").includes("Which moment should I start with?"));
    assert.ok(starters("editor").includes("How can I improve this edit?"));
    assert.ok(starters("analytics").includes("What seems to be working?"));
  });

  it("says what is happening while waiting, and warns about long questions", () => {
    assert.equal(waitingText(200), "Looking at this project…");
    assert.equal(waitingText(3000), "Thinking…");
    assert.equal(lengthNote("hi"), null);
    assert.equal(lengthNote("x".repeat(950)), "50 characters left");
    assert.equal(lengthNote("x".repeat(1003)), "3 characters too long");
  });
});
