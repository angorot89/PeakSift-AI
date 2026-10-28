// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  accentUsable,
  contrast,
  emphasisReadable,
  logoPlan,
  normalizeHex,
  placementNote,
  textOn,
} from "./brand-rules.ts";

describe("brand colours", () => {
  it("accepts hex only and normalizes it like the server", () => {
    assert.equal(normalizeHex("#ff3a72"), "#FF3A72");
    assert.equal(normalizeHex(" #f3a "), "#FF33AA");
    for (const bad of ["red", "#12345", "rgb(1,2,3)", "#ff3a7280", "#ff3a72;x"]) assert.equal(normalizeHex(bad), null, bad);
  });
  it("follows WCAG contrast and the server's readability rules", () => {
    assert.equal(Math.round(contrast("#FFFFFF", "#000000")), 21);
    assert.ok(emphasisReadable("#FFD43B"));
    assert.ok(!emphasisReadable("#1E3A8A")); // dark navy: captions keep their own colour
    assert.equal(textOn("#FFD43B"), "#111114");
    assert.equal(textOn("#1E3A8A"), "#FFFFFF");
    assert.ok(accentUsable("#F43F5E") && accentUsable("#FFD43B"));
  });
});

describe("logo placement", () => {
  it("moves away from same-side captions and waits for a top hook", () => {
    assert.deepEqual(logoPlan("bottom_right", "bottom", null), { corner: "top_right", moved: true, visibleFrom: 0 });
    assert.deepEqual(logoPlan("top_left", "top", null), { corner: "bottom_left", moved: true, visibleFrom: 0 });
    assert.equal(logoPlan("bottom_left", "center", null).moved, false);
    assert.equal(logoPlan("bottom_left", null, null).moved, false);
    assert.equal(logoPlan("top_right", "bottom", { position: "top", seconds: 2 }).visibleFrom, 2);
    assert.equal(logoPlan("top_right", "bottom", { position: "center", seconds: 2 }).visibleFrom, 0);
  });
  it("explains a move in the creator's words", () => {
    const plan = logoPlan("bottom_right", "bottom", null);
    assert.equal(placementNote(plan, "bottom_right"), "Shown top right so it stays clear of the captions (you chose bottom right).");
    assert.equal(placementNote(logoPlan("top_left", "bottom", null), "top_left"), null);
  });
});
