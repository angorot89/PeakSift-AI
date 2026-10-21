// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { bestSceneLabel, isPreparing, matchReason, searchNote, searchText, STRENGTH_LABEL } from "./visual-search.ts";

describe("visual search rules", () => {
  it("sends clean, bounded text", () => {
    assert.equal(searchText("  rocket   launch \n"), "rocket launch");
    assert.equal(searchText("   "), "");
    assert.equal(searchText("x".repeat(250)).length, 100);
  });

  it("labels strength tiers and reasons without numbers", () => {
    assert.equal(STRENGTH_LABEL.strong, "Strong match");
    assert.equal(STRENGTH_LABEL.possible, "Possible match");
    assert.equal(matchReason({ method: "visual" }), "Matched by what it shows");
    assert.equal(matchReason({ method: "metadata" }), "Matched by its name, description or tags");
    assert.equal(matchReason({ method: "visual_and_metadata" }), "Matched by what it shows and its details");
    for (const text of Object.values(STRENGTH_LABEL)) assert.doesNotMatch(text, /\d|%/);
  });

  it("knows which states are still preparing", () => {
    for (const state of ["not_indexed", "queued", "indexing", "stale"] as const) assert.equal(isPreparing(state), true);
    for (const state of ["ready", "failed", "unavailable", undefined, null] as const) assert.equal(isPreparing(state), false);
  });

  it("explains when visual search did not take part", () => {
    assert.equal(searchNote(null), null);
    assert.equal(searchNote({ visual_search_used: true, assets_preparing: 0 }), null);
    assert.equal(
      searchNote({ visual_search_used: true, assets_preparing: 1 }),
      "Visual search is still preparing for 1 visual. Names, descriptions and tags already work.",
    );
    assert.match(searchNote({ visual_search_used: false, assets_preparing: 3 }) ?? "", /preparing for 3 visuals/);
    assert.equal(
      searchNote({ visual_search_used: false, assets_preparing: 0 }),
      "Searching names, descriptions and tags only right now.",
    );
  });

  it("labels a video's best scene", () => {
    assert.equal(bestSceneLabel(8.4), "Best at 0:08");
    assert.equal(bestSceneLabel(65.9), "Best at 1:05");
    assert.equal(bestSceneLabel(null), null);
    assert.equal(bestSceneLabel(Number.NaN), null);
    assert.equal(bestSceneLabel(-1), null);
  });
});
