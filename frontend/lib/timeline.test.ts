import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  canvasWidth,
  filmFrameCount,
  filmFrameTimes,
  fractionAt,
  rulerLabel,
  seekForKey,
  tickStep,
  ticks,
  timeAtFraction,
  timecode,
  timeRange,
} from "./timeline.ts";

describe("timeline scale", () => {
  it("fits the whole Short when it can, and scrolls when a second would get too narrow", () => {
    assert.equal(canvasWidth(20, 900), 900);
    assert.equal(canvasWidth(60, 300), 60 * 28);
    assert.equal(canvasWidth(0, 300), 300);
  });

  it("picks a ruler step that keeps labels apart", () => {
    assert.equal(tickStep(20, 900), 2); // 45 px/s → 2 s steps (90 px)
    assert.equal(tickStep(60, 1680), 5); // 28 px/s → 5 s steps
    assert.equal(tickStep(8, 1200), 0.5); // 150 px/s → half seconds
    assert.deepEqual(ticks(10, 2), [0, 2, 4, 6, 8]);
    assert.deepEqual(ticks(9.1, 2), [0, 2, 4, 6, 8]);
  });

  it("maps positions and seconds both ways, clamped to the Short", () => {
    assert.equal(timeAtFraction(0.5, 20), 10);
    assert.equal(timeAtFraction(-1, 20), 0);
    assert.equal(timeAtFraction(2, 20), 20);
    assert.equal(fractionAt(5, 20), 0.25);
    assert.equal(fractionAt(25, 20), 1);
  });
});

describe("time labels", () => {
  it("reads like a player", () => {
    assert.equal(rulerLabel(0), "0:00");
    assert.equal(rulerLabel(65), "1:05");
    assert.equal(rulerLabel(2.5), "0:02.5");
    assert.equal(timecode(12.44), "0:12.4");
    assert.equal(timecode(75.06), "1:15.1");
    assert.equal(timeRange(12.4, 15.2), "0:12.4–0:15.2");
  });
});

describe("keyboard seeking", () => {
  it("moves by a second, five with Shift, and jumps to the ends", () => {
    assert.equal(seekForKey("ArrowRight", false, 3, 20), 4);
    assert.equal(seekForKey("ArrowLeft", true, 3, 20), 0);
    assert.equal(seekForKey("ArrowUp", true, 18, 20), 20);
    assert.equal(seekForKey("Home", false, 9, 20), 0);
    assert.equal(seekForKey("End", false, 9, 20), 20);
    assert.equal(seekForKey("a", false, 9, 20), null);
  });
});

describe("film strip", () => {
  it("uses a bounded number of frames from the middle of each slice", () => {
    assert.equal(filmFrameCount(200), 3);
    assert.equal(filmFrameCount(900), 10);
    assert.equal(filmFrameCount(5000), 12);
    assert.deepEqual(filmFrameTimes(20, 4), [2.5, 7.5, 12.5, 17.5]);
  });
});
