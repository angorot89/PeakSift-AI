// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  assetTimeAt,
  elementProblems,
  elementRequest,
  fulfills,
  insetRect,
  newElement,
  visualsKey,
  opacityAt,
  overlapProblems,
  visualsSummary,
  type AssetFacts,
  type VisualElementDraft,
  type VisualLayout,
} from "./visual-elements.ts";

const IMAGE: AssetFacts = { kind: "image", duration_seconds: null, width: 400, height: 300 };
const VIDEO: AssetFacts = { kind: "video", duration_seconds: 6, width: 1280, height: 720 };
const LAYOUT: VisualLayout = {
  output: { width: 1080, height: 1920 },
  margins: { top: 192, bottom: 422, left: 97, right: 97 },
  inset_width_fraction: { small: 0.34, medium: 0.44, large: 0.56, full: 1 },
  inset_max_aspect: 1.25,
  pip_border: 6,
  background: "#111113",
};

const el = (overrides: Partial<VisualElementDraft> = {}): VisualElementDraft => ({
  ...newElement("a", IMAGE, 2, 20),
  ...overrides,
});

describe("visual elements", () => {
  it("creates elements that fit the short", () => {
    const e = newElement("a", IMAGE, 19.9, 20);
    assert.equal(e.start_seconds, 19.5);
    assert.equal(e.end_seconds, 20);
    const v = newElement("v", { ...VIDEO, duration_seconds: 1.2 }, 1, 20);
    assert.equal(v.end_seconds, 2.2); // a short video gives a short element
  });

  it("sends only the options of the element's mode, rounded", () => {
    assert.deepEqual(elementRequest(el({ start_seconds: 2.004, end_seconds: 4.996 }), IMAGE), {
      asset_id: "a", mode: "cutaway", start_seconds: 2, end_seconds: 5, fit: "fill",
    });
    const pip = elementRequest(el({ mode: "pip", position: "center", transition: "fade", transition_seconds: 0.25 }), VIDEO);
    assert.equal(pip.position, "top_right");
    assert.equal(pip.fit, undefined);
    assert.equal(pip.loop, false);
    assert.equal(pip.transition_seconds, 0.25);
    assert.equal(elementRequest(el({ mode: "overlay", opacity: 0.456 }), IMAGE).opacity, 0.46);
  });

  it("mirrors the server's checks", () => {
    assert.deepEqual(elementProblems(el(), IMAGE, 20), []);
    assert.match(elementProblems(el({ end_seconds: 21 }), IMAGE, 20)[0], /after the end of the clip/);
    assert.match(elementProblems(el({ mode: "overlay" }), VIDEO, 20)[0], /Overlays use images/);
    assert.match(elementProblems(el({ asset_offset_seconds: 4 }), VIDEO, 20)[0], /shorter than the visual/);
    assert.deepEqual(elementProblems(el({ asset_offset_seconds: 4, loop: true }), VIDEO, 20), []);
    assert.match(elementProblems(el({ transition: "fade", transition_seconds: 0.5, end_seconds: 2.8 }), IMAGE, 20)[0], /half the visual/);
    assert.match(elementProblems(el(), undefined, 20)[0], /no longer in the project/);
  });

  it("allows one cutaway and one inset at a time", () => {
    const a = el({ key: "a" });
    const b = el({ key: "b", mode: "pip", start_seconds: 3, end_seconds: 6 });
    const c = el({ key: "c", start_seconds: 4, end_seconds: 6 });
    assert.equal(overlapProblems([a, b]).size, 0);
    assert.deepEqual([...overlapProblems([a, b, c]).keys()].sort(), ["a", "c"]);
  });

  it("ramps opacity like the renderer", () => {
    const fade = el({ start_seconds: 2, end_seconds: 4, transition: "fade", transition_seconds: 0.4 });
    assert.deepEqual([1.9, 2.1, 3, 3.8, 4].map((t) => Math.round(opacityAt(fade, t) * 100) / 100), [0, 0.25, 1, 0.5, 0]);
  });

  it("follows the video's offset and loops like -stream_loop", () => {
    const e = el({ start_seconds: 2, end_seconds: 10, asset_offset_seconds: 4, loop: true });
    assert.equal(assetTimeAt(e, 2, 6), 4);
    assert.equal(assetTimeAt(e, 5, 6), 1); // 4 + 3 = 7 → wrapped to 1
    assert.equal(assetTimeAt(e, 1, 6), null);
    assert.equal(assetTimeAt({ ...e, loop: false }, 3, 6), 5);
  });

  it("places insets like the renderer", () => {
    const rect = insetRect({ mode: "pip", size: "medium", position: "bottom_left" }, { width: 300, height: 300 }, LAYOUT);
    assert.deepEqual(rect, { x: 97, y: 1010, width: 488, height: 488, border: 6 });
    const overlay = insetRect({ mode: "overlay", size: "small", position: "center" }, { width: 200, height: 200 }, LAYOUT);
    assert.deepEqual(overlay, { x: 356, y: 776, width: 368, height: 368, border: 0 });
    // A full-frame overlay (an animated effect) covers the whole short, centred, whatever its position.
    const effect = insetRect({ mode: "overlay", size: "full", position: "top_left" }, { width: 720, height: 1280 }, LAYOUT);
    assert.deepEqual(effect, { x: 0, y: 0, width: 1080, height: 1920, border: 0 });
  });

  it("compares visuals like the server's fingerprint", () => {
    const requested = [elementRequest(el({ start_seconds: 2, end_seconds: 5 }), IMAGE)];
    const stored = [{ asset_id: "a", mode: "cutaway", start_seconds: 2.0, end_seconds: 5.0,
      asset_offset_seconds: 0, loop: false, fit: "fill" }]; // prettier-ignore
    assert.equal(visualsKey(requested), visualsKey(stored));
    assert.notEqual(visualsKey(requested), visualsKey([{ ...stored[0], fit: "fit" }]));
    assert.equal(visualsKey([]), "");
  });

  it("summarizes", () => {
    assert.equal(visualsSummary(0), null);
    assert.equal(visualsSummary(2), "2 visuals");
  });
});

describe("suggestion use", () => {
  const moment = { start: 10.2, end: 12.7 };
  const el = (start_seconds: number, end_seconds: number) => ({ start_seconds, end_seconds });

  it("a visual at the suggested moment fulfils it", () => {
    assert.equal(fulfills(el(10.2, 12.7), moment), true); // placed from the suggestion (or Auto Edit)
    assert.equal(fulfills(el(9.5, 11.5), moment), true); // nudged, still covers half
  });

  it("a visual elsewhere, or covering too little, does not", () => {
    assert.equal(fulfills(el(3, 6), moment), false);
    assert.equal(fulfills(el(12.0, 14.0), moment), false); // 0.7 s of 2.5 s
    assert.equal(fulfills(el(12.7, 14.0), moment), false); // touching is not covering
    assert.equal(fulfills(el(10, 12), { start: 5, end: 5 }), false);
  });
});

describe("transparent video overlays", () => {
  it("are allowed as overlays, opaque videos are not", () => {
    const element = { ...newElement("a", { ...VIDEO, has_alpha: true }, 0, 10, "overlay"), size: "full" as const };
    assert.deepEqual(elementProblems(element, { ...VIDEO, has_alpha: true }, 10), []);
    assert.ok(elementProblems(element, VIDEO, 10).some((p) => p.includes("transparent videos")));
    assert.ok(elementProblems({ ...element, mode: "pip" }, VIDEO, 10).includes("Only overlays can fill the frame."));
  });
});
