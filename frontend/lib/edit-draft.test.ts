// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { DEFAULT_DRAFT, draftFromConfiguration } from "./edit-draft.ts";

const CURRENT = { analysisId: "frame-1", trackId: "track-1" };

// A real `EditConfig.snapshot()` shape (backend app/services/clip_edit/config.py).
const FULL = {
  version: 1,
  aspect_ratio: "9:16",
  layout: "smart_reframe",
  output: { width: 1080, height: 1920 },
  reframe: { analysis_id: "frame-1" },
  captions: {
    enabled: true, style: "punch", position: "bottom", renderer: "caption_v2", timing: "aligned_word",
    safe_area: "general_social_v1", track_id: "track-1",
  },
  hook: { text: "Our bridge collapsed", style: "boxed", position: "top", duration: 2.5 },
  audio: {
    version: "audio_mix_v1", source_gain_db: -1.5, normalize: true, loudness: "social_v1",
    music: { asset_id: "m1", gain_db: -20, source_start_seconds: 3, loop: false, fade_in_seconds: 0.5,
             fade_out_seconds: 1, ducking: "strong" },
    sfx: [{ asset_id: "s1", at_seconds: 10.15, gain_db: -10 }],
  },
  visuals: {
    version: "visuals_v1",
    elements: [
      { asset_id: "a1", mode: "cutaway", start_seconds: 10.2, end_seconds: 12.7, fit: "fit", transition: "fade",
        transition_seconds: 0.4 },
      { asset_id: "a2", mode: "pip", start_seconds: 3, end_seconds: 6, position: "top_left", size: "large",
        asset_offset_seconds: 0.5, loop: true },
    ],
  },
};

describe("loading editor settings from a stored configuration", () => {
  it("reproduces every section exactly", () => {
    const { draft, notes } = draftFromConfiguration(FULL, CURRENT);
    assert.deepEqual(notes, []);
    assert.equal(draft.layout, "smart_reframe");
    assert.equal(draft.framingMode, "auto");
    assert.equal(draft.captions, true);
    assert.equal(draft.preset, "punch");
    assert.equal(draft.position, "bottom");
    assert.equal(draft.timing, "aligned_word");
    assert.deepEqual(
      [draft.hookOn, draft.hookText, draft.hookStyle, draft.hookPosition, draft.hookDuration],
      [true, "Our bridge collapsed", "boxed", "top", 2.5],
    );
    assert.deepEqual(draft.audio, {
      source_gain_db: -1.5,
      normalize: true,
      music: { asset_id: "m1", gain_db: -20, source_start_seconds: 3, loop: false, fade_in_seconds: 0.5,
               fade_out_seconds: 1, ducking: "strong" },
      sfx: [{ asset_id: "s1", at_seconds: 10.15, gain_db: -10 }],
    });
    assert.equal(draft.audioSection, true);
    const [cut, pip] = draft.visuals;
    assert.deepEqual([cut.asset_id, cut.mode, cut.start_seconds, cut.end_seconds, cut.fit, cut.transition, cut.transition_seconds],
      ["a1", "cutaway", 10.2, 12.7, "fit", "fade", 0.4]);
    assert.deepEqual([pip.mode, pip.position, pip.size, pip.asset_offset_seconds, pip.loop, pip.transition],
      ["pip", "top_left", "large", 0.5, true, "none"]);
    assert.notEqual(cut.key, pip.key);
  });

  it("restores a manual focal point", () => {
    const { draft } = draftFromConfiguration({ ...FULL, layout: "manual_crop", reframe: undefined, focus: { x: 0.31, y: 0.4 } }, CURRENT);
    assert.equal(draft.layout, "smart_reframe");
    assert.equal(draft.framingMode, "manual");
    assert.deepEqual(draft.focus, { x: 0.31, y: 0.4 });
  });

  it("restores captions off, no hook, no audio and no visuals as such", () => {
    const { draft, notes } = draftFromConfiguration({ version: 1, layout: "fit", captions: { enabled: false } }, CURRENT);
    assert.equal(draft.layout, "fit");
    assert.equal(draft.captions, false);
    assert.equal(draft.hookOn, false);
    assert.equal(draft.hookText, null); // keeps the editor's own suggestion
    assert.deepEqual(draft.audio, DEFAULT_DRAFT.audio);
    assert.equal(draft.audioSection, false);
    assert.deepEqual(draft.visuals, []);
    assert.deepEqual(notes, []);
  });

  it("keeps a normalize-only audio section (dropping it would change the render)", () => {
    const stored = { version: 1, layout: "fit", captions: { enabled: false },
                     audio: { version: "audio_mix_v1", source_gain_db: 0, normalize: true, music: null, sfx: [] } };
    const { draft } = draftFromConfiguration(stored, CURRENT);
    assert.equal(draft.audioSection, true);
    assert.equal(draft.audio.normalize, true);
  });

  it("says when phrase timing was stored", () => {
    const stored = { ...FULL, captions: { ...FULL.captions, timing: "phrase_fallback", track_id: undefined } };
    assert.equal(draftFromConfiguration(stored, CURRENT).draft.timing, "phrase_fallback");
  });

  it("maps classic caption styles and says so", () => {
    const classic = { version: 1, layout: "blur_background", captions: { enabled: true, style: "bold", position: "center" } };
    const { draft, notes } = draftFromConfiguration(classic, CURRENT);
    assert.equal(draft.preset, "punch");
    assert.equal(draft.timing, "phrase_fallback");
    assert.equal(draft.position, "center");
    assert.match(notes[0], /classic caption style/);
  });

  it("says when framing or word timing has changed since", () => {
    const { notes } = draftFromConfiguration(FULL, { analysisId: "frame-2", trackId: "track-2" });
    assert.deepEqual(notes, ["Framing uses this clip's current analysis.", "Captions use this clip's current word timing."]);
    const missing = draftFromConfiguration(FULL, { analysisId: null, trackId: null }).notes;
    assert.equal(missing.length, 2);
    assert.match(missing[0], /analyze the framing again/);
    assert.match(missing[1], /generate word sync/);
  });

  it("never throws on odd input", () => {
    for (const value of [null, undefined, {}, { layout: 7, captions: "yes", audio: [], visuals: { elements: [null, 4] } }]) {
      const { draft } = draftFromConfiguration(value as never, CURRENT);
      assert.equal(draft.layout, "blur_background");
      assert.deepEqual(draft.visuals, []);
    }
  });

  it("does not share state with the defaults", () => {
    const { draft } = draftFromConfiguration({ layout: "fit" }, CURRENT);
    draft.focus.x = 0.9;
    draft.audio.sfx.push({ asset_id: "x", at_seconds: 1, gain_db: 0 });
    assert.equal(DEFAULT_DRAFT.focus.x, 0.5);
    assert.deepEqual(DEFAULT_DRAFT.audio.sfx, []);
  });
});

describe("a branded version", () => {
  it("keeps its brand section exactly (without the version tag)", () => {
    const brand = { version: "brand_v1", name: "Amine Clips", logo: { asset_id: "a", corner: "top_left", size: "small" } };
    const { draft } = draftFromConfiguration({ layout: "fit", captions: { enabled: false }, brand }, { analysisId: null, trackId: null });
    assert.deepEqual(draft.brand, { name: "Amine Clips", logo: { asset_id: "a", corner: "top_left", size: "small" } });
    assert.equal(draftFromConfiguration({ layout: "fit" }, { analysisId: null, trackId: null }).draft.brand, null);
  });
});
