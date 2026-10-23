// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { menuIndex } from "./menu-keys.ts";

describe("menu keyboard movement", () => {
  it("moves and wraps with the arrow keys", () => {
    assert.equal(menuIndex("ArrowDown", 0, 3), 1);
    assert.equal(menuIndex("ArrowDown", 2, 3), 0);
    assert.equal(menuIndex("ArrowUp", 0, 3), 2);
    assert.equal(menuIndex("ArrowDown", -1, 3), 0);
    assert.equal(menuIndex("ArrowUp", -1, 3), 2);
  });
  it("jumps with Home and End and ignores other keys", () => {
    assert.equal(menuIndex("Home", 2, 3), 0);
    assert.equal(menuIndex("End", 0, 3), 2);
    assert.equal(menuIndex("a", 0, 3), null);
    assert.equal(menuIndex("ArrowDown", 0, 0), null);
  });
});
