// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  cutsFromConfiguration,
  cutsKey,
  cutsProblem,
  findPauses,
  keptRanges,
  normalizeCuts,
  outputDuration,
  recognizePauses,
  restorePart,
  segmentsOf,
  skipRemoved,
  toOutput,
  toSource,
  withPauses,
  type Range,
} from "./cuts.ts";

const close = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 1e-6, `${actual} ≈ ${expected}`);

describe("removed ranges", () => {
  it("are rounded, sorted and merged like the server does", () => {
    assert.deepEqual(normalizeCuts([[5, 6], [1.00049, 2], [1.5, 2.5], [2.52, 3]]), [[1, 3], [5, 6]]);
    assert.deepEqual(normalizeCuts([[1, 1.02]]), []);
    assert.deepEqual(normalizeCuts([[2, 1], [Number.NaN, 3]]), []);
  });

  it("map clip time to the Short's time and back", () => {
    const cuts: Range[] = [[1, 2], [4, 4.5]];
    assert.deepEqual(keptRanges(cuts, 6), [[0, 1], [2, 4], [4.5, 6]]);
    close(outputDuration(cuts, 6), 4.5);
    close(toOutput(cuts, 3), 2);
    close(toOutput(cuts, 1.5), 1);
    close(toOutput(cuts, 5), 3.5);
    close(toSource(cuts, 6, 2), 3);
    close(toSource(cuts, 6, 3.5), 5);
    for (const t of [0.2, 2.7, 4.6, 5.9]) close(toSource(cuts, 6, toOutput(cuts, t)), t);
  });

  it("tell playback where to continue", () => {
    const cuts: Range[] = [[1, 2]];
    assert.equal(skipRemoved(cuts, 0.5), 0.5);
    assert.equal(skipRemoved(cuts, 1), 2);
    assert.equal(skipRemoved(cuts, 1.7), 2);
    assert.equal(skipRemoved(cuts, 2), 2);
  });
});

describe("pauses", () => {
  const words = [
    { start: 0.6, end: 1.0 },
    { start: 1.1, end: 1.5 },
    { start: 2.5, end: 3.0 }, // a 1 s pause before it
    { start: 3.3, end: 3.8 }, // 0.3 s
  ];

  it("are the gaps longer than the threshold, keeping a little air next to the words", () => {
    const pauses = findPauses(words, 4.5, 0.5, 0.08);
    // Leading silence (up to 0.08 s before the first word), the 1 s pause and the trailing 0.7 s; the 0.3 s gap stays.
    assert.deepEqual(pauses, [[0, 0.52], [1.58, 2.42], [3.88, 4.5]]);
    assert.equal(findPauses(words, 4.5, 0.2, 0.08).length, 4);
    assert.deepEqual(findPauses([], 4), []);
  });

  it("replace earlier pause cuts but keep the creator's own deletions", () => {
    const old = findPauses(words, 4.5, 0.5);
    const manual: Range = [3.1, 3.25];
    const updated = withPauses(normalizeCuts([...old, manual]), findPauses(words, 4.5, 0.75), old);
    assert.ok(updated.some(([s, e]) => s === 3.1 && e === 3.25));
    assert.ok(!updated.some(([s]) => s === 3.88)); // the 0.7 s ending is under 0.75 now
  });
});

describe("a reopened version", () => {
  const words = [
    { start: 0.6, end: 1.0 },
    { start: 2.5, end: 3.0 },
  ];
  it("knows which of its cuts were pauses", () => {
    const pauses = findPauses(words, 4, 0.3);
    const manual: Range = [3.2, 3.4];
    const found = recognizePauses(normalizeCuts([...pauses, manual]), words, 4);
    assert.ok(found);
    assert.equal(found.pauseSeconds, 0.5); // 0.2–0.5 s find the same three pauses: the longest is kept
    assert.deepEqual(found.pauseCuts, pauses);
    assert.equal(recognizePauses([manual], words, 4), null);
  });
});

describe("restoring a part cut by hand", () => {
  it("keeps the pauses it had swallowed", () => {
    const pauses: Range[] = [[1, 1.5], [4, 4.6]];
    const cuts = normalizeCuts([...pauses, [3.5, 5]]); // the hand cut merged with the 4–4.6 pause
    assert.deepEqual(cuts, [[1, 1.5], [3.5, 5]]);
    assert.deepEqual(restorePart(cuts, pauses, [3.5, 5]), [[1, 1.5], [4, 4.6]]);
    assert.deepEqual(restorePart([[1, 1.5], [6, 7]], pauses, [6, 7]), [[1, 1.5]]);
  });
});

describe("segments", () => {
  it("split at the creator's points and at every cut", () => {
    const segments = segmentsOf([[1, 2]], [0.5, 3], 4);
    assert.deepEqual(
      segments.map((s) => [s.start, s.end, s.removed]),
      [[0, 0.5, false], [0.5, 1, false], [1, 2, true], [2, 3, false], [3, 4, false]],
    );
  });
});

describe("rules and storage", () => {
  it("refuse leaving less than a second", () => {
    assert.equal(cutsProblem([[0, 2.5]], 3), "Leave at least one second of the clip.");
    assert.equal(cutsProblem([[0, 1]], 3), null);
  });

  it("read the section from a stored configuration", () => {
    assert.deepEqual(cutsFromConfiguration({ cuts: { version: "cuts_v1", removed: [[2, 3], [0, 1]] } }), [[0, 1], [2, 3]]);
    assert.deepEqual(cutsFromConfiguration({}), []);
    assert.deepEqual(cutsFromConfiguration({ cuts: { removed: "x" } }), []);
    assert.equal(cutsKey([[2, 3], [0, 1]]), cutsKey([[0, 1], [2, 3]]));
  });
});
