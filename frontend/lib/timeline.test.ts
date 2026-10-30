import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  canvasWidth,
  itemTooltip,
  renderState,
  activeAt,
  representativeTime,
  dragTimes,
  editableEdges,
  keyEdit,
  roundTime,
  snapDelta,
  captionRegions,
  musicEnd,
  timelineItems,
  toolForItem,
  usesInsetLane,
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

describe("timeline items", () => {
  const input = {
    duration: 15,
    hook: { on: true, text: "Four seconds ahead", seconds: 2.5 },
    visuals: [
      { key: "a", mode: "cutaway" as const, start: 4, end: 6.5, name: "lava-pit.png" },
      { key: "b", mode: "pip" as const, start: 8, end: 11, name: "controller.png" },
      { key: "c", mode: "overlay" as const, start: 12, end: 20, name: "controller.png" },
    ],
    sfx: [{ name: "Whoosh", at: 3, seconds: 0.6 }, { name: "Whoosh", at: 14.9, seconds: null }],
    music: { name: "chill-bed.mp3", end: 15 },
  };

  it("derives every item from the editor's settings, on its track and lane", () => {
    const items = timelineItems(input);
    assert.deepEqual(items.map((i) => `${i.track}/${i.lane}/${i.label}`), [
      "opening/0/Hook", "visuals/0/B-roll", "visuals/1/PiP", "visuals/1/Overlay",
      "sound/0/Whoosh", "sound/0/Whoosh", "music/0/chill-bed.mp3",
    ]);
    assert.deepEqual(items[0].ref, { type: "hook" });
    assert.deepEqual(items[1].ref, { type: "visual", key: "a" });
    assert.deepEqual(items[4].ref, { type: "sfx", index: 0 });
    assert.ok(usesInsetLane(items));
  });

  it("clamps to the Short and gives sound effects their length", () => {
    const items = timelineItems(input);
    assert.equal(items[3].end, 15); // an overlay past the end is drawn to the end
    assert.equal(items[4].end, 3.6);
    assert.equal(items[5].end, 15); // unknown length: a short marker, clamped
  });

  it("leaves out what is off", () => {
    const items = timelineItems({ ...input, hook: { ...input.hook, on: false }, visuals: [], sfx: [], music: null });
    assert.deepEqual(items, []);
    assert.equal(usesInsetLane(items), false);
  });

  it("knows where the music is heard", () => {
    assert.equal(musicEnd(true, 8, 0, 15), 15);
    assert.equal(musicEnd(false, 8, 2, 15), 6);
    assert.equal(musicEnd(false, 40, 0, 15), 15);
  });

  it("groups caption lines into readable regions", () => {
    const cues = [{ start: 0.2, end: 1.4 }, { start: 1.6, end: 3 }, { start: 5, end: 6 }];
    assert.deepEqual(captionRegions(cues), [{ start: 0.2, end: 3, lines: 2 }, { start: 5, end: 6, lines: 1 }]);
  });
});

describe("item tools", () => {
  it("opens the tool that edits each item", () => {
    assert.equal(toolForItem({ type: "hook" }), "opening");
    assert.equal(toolForItem({ type: "visual", key: "a" }), "visuals");
    assert.equal(toolForItem({ type: "sfx", index: 0 }), "sound");
    assert.equal(toolForItem({ type: "music" }), "sound");
  });
});

describe("editing on the timeline", () => {
  it("lets only supported timing change", () => {
    assert.deepEqual(editableEdges("cutaway"), { move: true, start: true, end: true });
    assert.deepEqual(editableEdges("sfx"), { move: true, start: false, end: false });
    assert.deepEqual(editableEdges("hook"), { move: false, start: false, end: true });
    assert.deepEqual(editableEdges("music"), { move: false, start: false, end: false });
  });

  it("moves inside the Short, keeping the length", () => {
    const bounds = { duration: 15, minLength: 0.5 };
    assert.deepEqual(dragTimes("move", 4, 6.5, 2, bounds), { start: 6, end: 8.5 });
    assert.deepEqual(dragTimes("move", 4, 6.5, -10, bounds), { start: 0, end: 2.5 });
    assert.deepEqual(dragTimes("move", 4, 6.5, 20, bounds), { start: 12.5, end: 15 });
  });

  it("resizes without going under the minimum or past the end", () => {
    const bounds = { duration: 15, minLength: 0.5 };
    assert.deepEqual(dragTimes("start", 4, 6.5, 5, bounds), { start: 6, end: 6.5 });
    assert.deepEqual(dragTimes("start", 4, 6.5, -9, bounds), { start: 0, end: 6.5 });
    assert.deepEqual(dragTimes("end", 4, 6.5, 30, bounds), { start: 4, end: 15 });
    assert.deepEqual(dragTimes("end", 0, 2.5, 4, { duration: 15, minLength: 0.5, maxLength: 5 }), { start: 0, end: 5 });
  });

  it("snaps the nearest edge gently, and only when close", () => {
    assert.deepEqual(snapDelta([4, 6.5], 1.4, [8], 0.2), { delta: 1.5, point: 8 });
    assert.deepEqual(snapDelta([4, 6.5], 1, [8], 0.2), { delta: 1, point: null });
    const near = snapDelta([4], 0.95, [5.3, 4.9], 0.2);
    assert.equal(near.point, 4.9);
    assert.ok(Math.abs(near.delta - 0.9) < 1e-9);
  });

  it("stores times to the nearest 0.05 s", () => {
    assert.equal(roundTime(4.123), 4.1);
    assert.equal(roundTime(4.126), 4.15);
  });

  it("maps keys to supported edits", () => {
    const visual = editableEdges("pip");
    assert.deepEqual(keyEdit("ArrowRight", false, false, visual), { mode: "move", delta: 0.1 });
    assert.deepEqual(keyEdit("ArrowLeft", true, true, visual), { mode: "end", delta: -1 });
    assert.deepEqual(keyEdit("ArrowRight", false, false, editableEdges("hook")), { mode: "end", delta: 0.1 });
    assert.equal(keyEdit("ArrowRight", false, true, editableEdges("sfx")), null);
    assert.equal(keyEdit("ArrowUp", false, false, visual), null);
  });
});

describe("preview sync", () => {
  it("shows a representative moment of the selected item", () => {
    assert.equal(representativeTime({ start: 4, end: 6, ref: { type: "visual", key: "a" } }), 5);
    assert.equal(representativeTime({ start: 3, end: 3.6, ref: { type: "sfx", index: 0 } }), 2.5);
    assert.equal(representativeTime({ start: 0.2, end: 0.8, ref: { type: "sfx", index: 1 } }), 0);
    assert.equal(representativeTime({ start: 0, end: 2, ref: { type: "hook" } }), 0);
    assert.equal(representativeTime({ start: 0, end: 15, ref: { type: "music" } }), null);
  });
  it("uses the preview's half-open interval", () => {
    assert.equal(activeAt(4, 6, 4), true);
    assert.equal(activeAt(4, 6, 6), false);
    assert.equal(activeAt(4, 6, 3.99), false);
  });
});

describe("polish", () => {
  it("writes tooltips creators can read", () => {
    assert.equal(itemTooltip({ kind: "cutaway", label: "B-roll", start: 12.4, end: 15.2 }, 30), "B-roll · 0:12.4–0:15.2");
    assert.equal(itemTooltip({ kind: "sfx", label: "Whoosh", start: 10.15, end: 10.75 }, 30), "Whoosh · 0:10.2");
    assert.equal(itemTooltip({ kind: "music", label: "chill-bed.mp3", start: 0, end: 30 }, 30), "chill-bed.mp3 · Full Short");
    assert.equal(itemTooltip({ kind: "music", label: "intro.mp3", start: 0, end: 12 }, 30), "intro.mp3 · 0:00.0–0:12.0");
  });
  it("says the render state honestly (no autosave)", () => {
    const base = { blocked: false, stuck: false, active: false, ready: false };
    assert.equal(renderState(base), "unrendered");
    assert.equal(renderState({ ...base, ready: true }), "rendered");
    assert.equal(renderState({ ...base, active: true }), "rendering");
    assert.equal(renderState({ ...base, stuck: true, active: true }), "attention");
    assert.equal(renderState({ ...base, blocked: true, ready: true }), "blocked");
  });
});

describe("hardening", () => {
  const bounds = { duration: 15, minLength: 0.5 };
  it("keeps an element at 0 s and one ending exactly at the end inside the Short", () => {
    assert.deepEqual(dragTimes("move", 0, 2, -1, bounds), { start: 0, end: 2 });
    assert.deepEqual(dragTimes("move", 13, 15, 1, bounds), { start: 13, end: 15 });
    assert.deepEqual(dragTimes("end", 13, 15, 0.5, bounds), { start: 13, end: 15 });
  });
  it("never makes an element shorter than the minimum, even when dragged past itself", () => {
    assert.deepEqual(dragTimes("end", 4, 4.5, -3, bounds), { start: 4, end: 4.5 });
    assert.deepEqual(dragTimes("start", 4, 4.5, 3, bounds), { start: 4, end: 4.5 });
  });
  it("lets two elements touch (adjacent is not overlapping) by snapping to the other's edge", () => {
    const snapped = snapDelta([6, 8.5], 0.45, [9, 12], 0.1); // 8.5 + 0.45 = 8.95 → 9
    assert.equal(snapped.point, 9);
    const next = dragTimes("move", 6, 8.5, snapped.delta, bounds);
    assert.ok(Math.abs(next.end - 9) < 1e-9);
  });
  it("stays smooth with many caption lines: one region per run of lines, not one per word", () => {
    const cues = Array.from({ length: 120 }, (_, i) => ({ start: i * 0.5, end: i * 0.5 + 0.45 }));
    const regions = captionRegions(cues);
    assert.equal(regions.length, 1);
    assert.equal(regions[0].lines, 120);
  });
  it("handles a very short Short", () => {
    assert.equal(canvasWidth(1.2, 800), 800);
    assert.deepEqual(ticks(1.2, tickStep(1.2, 800)), [0, 0.5, 1]);
  });
});
