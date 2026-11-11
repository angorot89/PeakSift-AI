// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { labelChanges, labelLine, labelProblem, labelsOf } from "./asset-labels.ts";
import { splitLocal } from "./visual-search.ts";

const names = { localLabel: "Moroccan", categories: { cafe: "Café" }, origins: { cc0: "CC0 (no rights reserved)" } };

describe("asset labels", () => {
  it("defaults to the creator's own Global upload", () => {
    assert.deepEqual(labelsOf({}), { origin: "creator_upload", license_note: null, market: "global", category: null, location: null });
  });
  it("sends only what changed, and a Global asset never keeps a location", () => {
    const before = labelsOf({ market: "ma", location: "Rabat" });
    assert.deepEqual(labelChanges(before, { ...before, market: "global" }), { market: "global", location: null });
    assert.deepEqual(labelChanges(before, before), {});
  });
  it("asks for the licence of a licensed asset", () => {
    assert.match(labelProblem(labelsOf({ origin: "licensed" })) ?? "", /licence/);
    assert.equal(labelProblem(labelsOf({ origin: "licensed", license_note: "Envato #42" })), null);
  });
  it("describes a local asset in one line", () => {
    assert.equal(labelLine(labelsOf({ market: "ma", category: "cafe", location: "Casablanca", origin: "cc0" }), names), "Moroccan · Café · Casablanca · CC0 (no rights reserved)");
    assert.equal(labelLine(labelsOf({}), names), "");
  });
});

describe("local first, never burying a better Global match", () => {
  const hit = (id: string, strength: "strong" | "possible", local: boolean) => ({ id, local, match: { strength } });
  it("splits strong matches into local and Global, weaker ones below both", () => {
    const split = splitLocal([hit("l1", "strong", true), hit("g1", "strong", false), hit("l2", "possible", true), hit("g2", "possible", false)]);
    assert.deepEqual(split && [split.local.map((h) => h.id), split.global.map((h) => h.id), split.more.map((h) => h.id)], [["l1"], ["g1"], ["l2", "g2"]]);
  });
  it("leaves Global projects (no local hits) exactly as they were", () => {
    assert.equal(splitLocal([hit("g1", "strong", false)]), null);
  });
});
