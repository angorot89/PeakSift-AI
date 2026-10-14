import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { cueAt, parseState, stateAt, type PreviewCue } from "./caption-timing.ts";

const word = (text: string, start: number, end: number, attached = false) => ({ text, start, end, attached });
const CUES: PreviewCue[] = [
  { start: 0.4, end: 1.9, timed: true, lines: [[word("ONE", 0.4, 0.9), word("TWO", 0.9, 1.4)], [word("THREE", 1.4, 1.9)]] },
  { start: 2.0, end: 3.0, timed: false, lines: [[word("phrase", 2.0, 3.0), word("only", 2.0, 3.0)]] },
  { start: 3.0, end: 4.0, timed: true, lines: [[word("https://exam", 3.0, 4.0), word("ple.com", 3.0, 4.0, true)]] },
];

describe("caption timing", () => {
  it("finds the cue on screen, with exact boundaries", () => {
    assert.equal(cueAt(CUES, 0.39), -1);
    assert.equal(cueAt(CUES, 0.4), 0);
    assert.equal(cueAt(CUES, 1.95), -1);
    assert.equal(cueAt(CUES, 3.0), 2); // back-to-back cues: the next one owns the boundary
    assert.equal(cueAt([], 1), -1);
  });

  it("emphasises exactly the word being spoken", () => {
    assert.equal(stateAt(CUES, 0.5), "0|0:0");
    assert.equal(stateAt(CUES, 0.9), "0|0:1");
    assert.equal(stateAt(CUES, 1.5), "0|1:0");
    assert.deepEqual(parseState(stateAt(CUES, 1.0)), { cue: 0, active: new Set(["0:1"]) });
  });

  it("never highlights phrase-timed captions", () => {
    assert.equal(stateAt(CUES, 2.5), "1|");
    assert.equal(parseState("1|")?.active.size, 0);
  });

  it("lights up every piece of a split word together", () => {
    assert.equal(stateAt(CUES, 3.5), "2|0:0,0:1");
  });

  it("is empty between cues", () => {
    assert.equal(stateAt(CUES, 1.95), "");
    assert.equal(parseState(""), null);
  });
});
