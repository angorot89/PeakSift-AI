import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { canSearch, emptySearch, matchSummary } from "./find-clips-rules.ts";

describe("find clips", () => {
  it("says what a result is based on", () => {
    assert.equal(matchSummary({ matched: ["pricing"], related: [] }), "Heard: pricing");
    assert.equal(matchSummary({ matched: ["cat", "keyboard"], related: ["funny"] }), "Heard: cat, keyboard · related: funny");
    assert.equal(matchSummary({ matched: [], related: ["funny", "laugh"] }), "Related words heard: funny, laugh");
    assert.equal(matchSummary({ matched: [], related: [] }), "");
  });

  it("explains an empty search", () => {
    assert.match(emptySearch([], []).title, /Add a word/);
    const none = emptySearch(["pricing"], ["cost"]);
    assert.match(none.title, /Nothing in this video/);
    assert.match(none.description, /“pricing”, “cost”/);
  });

  it("needs two real characters", () => {
    assert.equal(canSearch(" a "), false);
    assert.equal(canSearch("ai"), true);
  });
});
