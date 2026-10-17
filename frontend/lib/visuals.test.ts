// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { filterVisuals, formatVisualDuration, orientationLabel, parseTagText } from "./visual-rules.ts";

describe("visual asset rules", () => {
  it("formats B-roll durations", () => {
    assert.equal(formatVisualDuration(8.4), "0:08");
    assert.equal(formatVisualDuration(65), "1:05");
    assert.equal(formatVisualDuration(-1), "0:00");
    assert.equal(formatVisualDuration(Number.NaN), "0:00");
  });

  it("describes orientation", () => {
    assert.equal(orientationLabel({ width: 1920, height: 1080 }), "Landscape");
    assert.equal(orientationLabel({ width: 1080, height: 1920 }), "Portrait");
    assert.equal(orientationLabel({ width: 1000, height: 1030 }), "Square");
  });

  it("filters by kind and searches every word of the name", () => {
    const assets = [
      { kind: "image" as const, display_name: "Moon Surface.png" },
      { kind: "video" as const, display_name: "moon launch.mp4" },
      { kind: "image" as const, display_name: "rocket_100%.jpg" },
    ];
    const names = (filter: "all" | "image" | "video", q: string) =>
      filterVisuals(assets, filter, q).map((a) => a.display_name);
    assert.deepEqual(names("all", ""), ["Moon Surface.png", "moon launch.mp4", "rocket_100%.jpg"]);
    assert.deepEqual(names("image", "MOON"), ["Moon Surface.png"]);
    assert.deepEqual(names("all", "moon launch"), ["moon launch.mp4"]);
    assert.deepEqual(names("video", "rocket"), []);
    assert.deepEqual(names("all", "100%"), ["rocket_100%.jpg"]);
  });

  it("searches descriptions and tags too, and parses tag text", () => {
    const assets = [
      { kind: "video" as const, display_name: "clip-7.mp4", description: "NASA-style launch", tags: ["rocket"] },
      { kind: "image" as const, display_name: "a.png", description: "", tags: [] },
    ];
    assert.deepEqual(filterVisuals(assets, "all", "rocket launch").map((a) => a.display_name), ["clip-7.mp4"]);
    assert.deepEqual(parseTagText(" Rocket, space ,, rocket,Launch "), ["rocket", "space", "launch"]);
  });
});
