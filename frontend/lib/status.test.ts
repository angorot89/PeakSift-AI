// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { humanStatus } from "./status.ts";

describe("human status language", () => {
  it("speaks in four plain states", () => {
    assert.deepEqual(humanStatus("queued"), { label: "Waiting", tone: "waiting" });
    assert.deepEqual(humanStatus("completed"), { label: "Ready", tone: "success" });
    assert.deepEqual(humanStatus("ready"), { label: "Ready", tone: "success" });
    assert.deepEqual(humanStatus("failed"), { label: "Needs attention", tone: "danger" });
  });
  it("names a recognisable step while working", () => {
    assert.equal(humanStatus("transcribing").label, "Transcribing");
    assert.equal(humanStatus("analyzing").label, "Finding moments");
  });
  it("never shows an internal name", () => {
    assert.deepEqual(humanStatus("some_new_internal_state"), { label: "Processing", tone: "processing" });
    assert.deepEqual(humanStatus("rendering", true), { label: "Needs attention", tone: "warning" });
  });
});
