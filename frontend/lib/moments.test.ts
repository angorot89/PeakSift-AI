import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { emptyMoments, momentCount, momentQuery } from "./moments.ts";

const COUNTS = { active: 4, top: 2, saved: 1, dismissed: 3 };

describe("moment filters", () => {
  it("asks the API for the right view or decision", () => {
    assert.deepEqual(momentQuery("all"), { view: "active" });
    assert.deepEqual(momentQuery("top"), { view: "top" });
    assert.deepEqual(momentQuery("saved"), { decision: "saved" });
    assert.deepEqual(momentQuery("dismissed"), { decision: "dismissed" });
  });

  it("counts All without dismissed moments", () => {
    assert.equal(momentCount(COUNTS, "all"), 4);
    assert.equal(momentCount(COUNTS, "dismissed"), 3);
  });

  it("offers a way out of an empty filter only when there is one", () => {
    assert.equal(emptyMoments("all", { ...COUNTS, active: 0 }).offer, "dismissed");
    assert.equal(emptyMoments("all", { active: 0, top: 0, saved: 0, dismissed: 0 }).offer, undefined);
    assert.equal(emptyMoments("top", { ...COUNTS, top: 0 }).offer, "all");
    assert.equal(emptyMoments("top", { active: 0, top: 0, saved: 0, dismissed: 2 }).offer, undefined);
    assert.equal(emptyMoments("saved", COUNTS).title, "Nothing saved yet");
  });
});
