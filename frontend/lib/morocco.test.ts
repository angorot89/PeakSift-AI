// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { defaultMode, defaultModeLabel, KIT_TABS, kitFilters, kitMatches, kitTab, localFirst, MODES, MOROCCO_SECTIONS } from "./morocco.ts";

describe("Morocco Mode", () => {
  it("shows only what really exists — never trends, figures or invented media", () => {
    assert.ok(!MOROCCO_SECTIONS.some((s) => s.key.includes("trend")));
    for (const s of MOROCCO_SECTIONS) {
      assert.doesNotMatch(`${s.title} ${s.promise}`, /\d|%|real-time|trending/i, s.key);
    }
    assert.match(MOROCCO_SECTIONS.find((s) => s.key === "darija_hooks")!.promise, /never Darija you didn't say/);
  });

  it("switches between Global and Morocco Mode, which keeps Global", () => {
    assert.deepEqual(MODES.map((m) => [m.market, m.href]), [["global", "/home"], ["ma", "/morocco"]]);
    // The saved default for new projects, shown beside the switch whichever page is open.
    assert.equal(defaultMode("ma"), "morocco");
    assert.equal(defaultMode("global"), "global");
    assert.equal(defaultMode(undefined), "global");
    assert.equal(defaultModeLabel(defaultMode("ma")), "Morocco Mode");
  });

  it("has a kit with four tabs, opening on visuals by default", () => {
    assert.deepEqual(KIT_TABS.map((t) => t.key), ["visuals", "sounds", "hooks", "templates"]);
    assert.equal(kitTab("sounds"), "sounds");
    assert.equal(kitTab("trends"), "visuals");
    assert.equal(kitTab(null), "visuals");
  });

  it("offers filters only from the metadata the creator's assets really carry", () => {
    const names = { cafe: "Café", coast: "Coast" };
    assert.deepEqual(kitFilters([], names), []);
    assert.deepEqual(
      kitFilters([{ category: "cafe", location: "Casablanca" }, { category: "cafe", location: null }, { category: null, location: "Agadir" }], names),
      [
        { key: "location:Agadir", label: "Agadir" },
        { key: "category:cafe", label: "Café" },
        { key: "location:Casablanca", label: "Casablanca" },
      ],
    );
  });

  it("searches names, tags, places and categories, ignoring accents", () => {
    const names = { cafe: "Café" };
    const item = { display_name: "morning.jpg", tags: ["l9hwa"], category: "cafe", location: "Casablanca" };
    assert.ok(kitMatches(item, "cafe casablanca", null, names));
    assert.ok(kitMatches(item, "l9hwa", "category:cafe", names));
    assert.ok(!kitMatches(item, "", "location:Rabat", names));
  });

  it("keeps local matches first and drops nothing", () => {
    const items = [{ id: "g1", local: false }, { id: "m1", local: true }, { id: "g2", local: false }, { id: "m2", local: true }];
    assert.deepEqual(localFirst(items).map((i) => i.id), ["m1", "m2", "g1", "g2"]);
  });
});
