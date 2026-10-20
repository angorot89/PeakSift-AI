// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  basedOn,
  formatSpan,
  isPlanActive,
  missingInputs,
  planSections,
  planSteps,
  plannerNote,
  type AutoEditPlan,
  type PlanConfidence,
} from "./auto-edit-rules.ts";

const CONFIDENCE: PlanConfidence = {
  planner: "local_ai",
  fallback: false,
  framing: "high",
  word_timing: true,
  phrase_timing: true,
  broll_method: "local_ai",
  broll_suggestions: 1,
  matched_assets: 2,
};

const states = (status: Parameters<typeof planSteps>[0]) => planSteps(status).map((s) => s.state);

describe("Auto Edit plan display", () => {
  it("shows honest stages, never a percentage", () => {
    assert.deepEqual(states("queued"), ["current", "todo", "todo", "todo"]);
    assert.deepEqual(states("analyzing"), ["current", "todo", "todo", "todo"]);
    assert.deepEqual(states("planning"), ["done", "current", "todo", "todo"]);
    assert.deepEqual(states("validating"), ["done", "done", "current", "todo"]);
    assert.deepEqual(states("ready"), ["done", "done", "done", "done"]);
    assert.deepEqual(states("applied"), ["done", "done", "done", "done"]);
    assert.deepEqual(states("failed"), ["failed", "todo", "todo", "todo"]);
    assert.deepEqual(planSteps("ready").map((s) => s.label)[3], "Plan ready");
  });

  it("knows which plans are still running", () => {
    assert.equal(isPlanActive("planning"), true);
    assert.equal(isPlanActive("ready"), false);
    assert.equal(isPlanActive("failed"), false);
  });

  it("says who planned it", () => {
    assert.match(plannerNote(CONFIDENCE) ?? "", /local AI/);
    assert.match(plannerNote({ ...CONFIDENCE, planner: "rules", fallback: true }) ?? "", /unavailable/);
    assert.match(plannerNote({ ...CONFIDENCE, planner: "rules" }) ?? "", /built-in rules/);
    assert.equal(plannerNote(null), null);
  });

  it("lists only true facts, and offers what is missing", () => {
    assert.deepEqual(basedOn(CONFIDENCE), [
      "face framing (strong)",
      "word timing",
      "1 B-roll suggestion",
      "2 matching assets",
    ]);
    const bare = { ...CONFIDENCE, framing: null, word_timing: false, broll_suggestions: 0, matched_assets: 0 };
    assert.deepEqual(basedOn(bare), ["transcript timing"]);
    assert.equal(missingInputs(bare).length, 3);
    assert.deepEqual(missingInputs(CONFIDENCE), []);
  });

  it("orders sections and skips missing ones", () => {
    const plan = {
      explanations: {
        version: "v1",
        sections: {
          audio: { choice: "Original audio, normalized", reason: "Voice first." },
          layout: { choice: "Smart Reframe", reason: "Strong tracking." },
        },
        notes: [],
      },
    } as unknown as AutoEditPlan;
    assert.deepEqual(planSections(plan).map((s) => s.title), ["Framing", "Audio"]);
    assert.deepEqual(planSections({ explanations: null } as unknown as AutoEditPlan), []);
  });

  it("formats moments", () => {
    assert.equal(formatSpan(10.2, 12.7), "0:10.2–0:12.7");
    assert.equal(formatSpan(65, 71.5), "1:05.0–1:11.5");
  });
});
