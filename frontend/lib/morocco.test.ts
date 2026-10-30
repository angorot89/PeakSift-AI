import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { KIT_TABS, kitFilters, localFirst, MOROCCO_CAPABILITIES, moroccoPreviewEnabled } from "./morocco.ts";

describe("Morocco Mode (preview)", () => {
  it("is off unless the build turns it on", () => {
    assert.equal(moroccoPreviewEnabled(undefined), false);
    assert.equal(moroccoPreviewEnabled("0"), false);
    assert.equal(moroccoPreviewEnabled("1"), true);
    assert.equal(moroccoPreviewEnabled("true"), true);
  });

  it("claims no Moroccan capability until real data exists", () => {
    assert.ok(MOROCCO_CAPABILITIES.every((c) => c.available === false));
    // Honest copy: no figures, percentages or "real-time" claims.
    for (const c of MOROCCO_CAPABILITIES) {
      assert.doesNotMatch(`${c.title} ${c.promise}`, /\d|%|real-time|trending now/i, c.key);
    }
  });

  it("points every unavailable capability at what works today, when something does", () => {
    for (const c of MOROCCO_CAPABILITIES) {
      if (c.today) assert.match(c.today.href, /^\/(projects|brand|home)$/);
    }
  });

  it("ships no place or topic filters without a library behind them", () => {
    assert.deepEqual(kitFilters(), []);
    assert.deepEqual(kitFilters([{ key: "local_assets", title: "", promise: "", available: true, today: null }]), ["All"]);
  });

  it("lists every Creator Kit tab against the capability it needs", () => {
    assert.deepEqual(KIT_TABS.map((t) => t.label), ["Images", "B-roll", "Sounds", "Hooks", "Templates"]);
    const keys = new Set(MOROCCO_CAPABILITIES.map((c) => c.key));
    assert.ok(KIT_TABS.every((t) => keys.has(t.needs)));
  });

  it("shows Moroccan matches first, then global alternatives, dropping none", () => {
    const items = [{ id: 1, local: false }, { id: 2, local: true }, { id: 3, local: false }, { id: 4, local: true }];
    assert.deepEqual(localFirst(items).map((i) => i.id), [2, 4, 1, 3]);
  });
});
