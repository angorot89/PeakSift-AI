// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { BLANK, freeHookPositions, resolved, sameSettings, startFrom, summary } from "./template-rules.ts";

const PUNCHY = { recipe: "punchy" as const, label: "Punchy", description: "", config: { ...BLANK, caption_preset: "punch" as const, caption_position: "bottom" as const, hook_style: "headline" as const, hook_seconds: 2 } };

describe("template settings", () => {
  it("resolve empty settings from the starting style for the preview", () => {
    const own = { ...BLANK, caption_preset: "minimal" as const };
    assert.equal(resolved(own, PUNCHY.config).preset, "minimal"); // the template wins
    assert.equal(resolved(BLANK, PUNCHY.config).preset, "punch"); // else the style's own
    assert.equal(resolved(BLANK, null).preset, "focus");
    assert.equal(resolved({ ...BLANK, caption_position: "top" }, null).hookPosition, "center");
  });
  it("describe a template in a few words", () => {
    assert.equal(summary(PUNCHY.config, true), "Punch captions · Headline hook · B-roll as the style suggests · Logo");
    assert.equal(summary({ ...BLANK, captions: false, hook: false, broll: "none", end_card: true, end_card_seconds: 1.5 }, false), "No captions · No hook · No B-roll · End card +1.5s");
    assert.equal(summary({ ...BLANK, framing: "smart_reframe", broll: "light" }, false), "Smart Reframe · Style's captions · Light B-roll");
  });
  it("start from a recipe or blank, compare, and keep the hook clear of captions", () => {
    assert.equal(startFrom(PUNCHY).caption_preset, "punch");
    assert.deepEqual(startFrom(null), BLANK);
    assert.ok(sameSettings({ ...BLANK, version: "template_v1" }, BLANK));
    assert.ok(!sameSettings({ ...BLANK, broll: "none" }, BLANK));
    assert.deepEqual(freeHookPositions("top"), ["center"]);
    assert.deepEqual(freeHookPositions(null), ["top", "center"]);
  });
});
