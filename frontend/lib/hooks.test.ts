// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { hookTargets, langOf, methodLabel, noteText } from "./hooks-rules.ts";

describe("hook languages", () => {
  it("always starts from the clip's own words, never forcing Darija", () => {
    assert.equal(hookTargets("ma", "french")[0].key, "original");
    assert.equal(hookTargets("global", "english")[0].key, "original");
  });
  it("puts Darija first for Moroccan or Darija projects, last otherwise — but always offers it", () => {
    assert.deepEqual(hookTargets("ma", null).slice(1, 3).map((t) => t.key), ["darija_arabic", "darija_latin"]);
    assert.deepEqual(hookTargets("global", "mixed").slice(1, 3).map((t) => t.key), ["darija_arabic", "darija_latin"]);
    const global = hookTargets("global", "english").map((t) => t.key);
    assert.equal(global[1], "english");
    assert.ok(global.includes("darija_latin"));
  });
  it("labels local AI suggestions as needing a check, and transcript ideas as the clip's own", () => {
    const base = { text: "x", kind: "question" as const, language: "darija", script: "arabic" as const, source: "x", meaning: null };
    assert.match(methodLabel({ ...base, method: "local_ai" }), /check it says the same/);
    assert.match(methodLabel({ ...base, method: "transliteration" }), /check the spelling/);
    assert.match(noteText("unsupported") ?? "", /Darija comes only from words you said/);
    assert.equal(methodLabel({ ...base, method: "transcript" }), "Your clip's own words");
    assert.equal(langOf({ language: "darija", script: "arabic" }), "ar");
    assert.equal(langOf({ language: "darija", script: "latin" }), undefined);
    assert.equal(noteText(null), null);
    assert.match(noteText("unavailable") ?? "", /isn't available/);
  });
});
