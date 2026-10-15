import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  audioFromConfiguration,
  audioSummary,
  crossedCues,
  DEFAULT_MUSIC,
  musicLevelAt,
  musicPositionAt,
  musicTimeline,
  normalizeAudio,
  sameAudio,
  type AudioRequest,
} from "./audio-mix.ts";

const music = { asset_id: "m", ...DEFAULT_MUSIC };
const full: AudioRequest = {
  source_gain_db: -1.54,
  normalize: true,
  music: { ...music, gain_db: -18.04, source_start_seconds: 12.504 },
  sfx: [
    { asset_id: "b", at_seconds: 3.214, gain_db: -6 },
    { asset_id: "a", at_seconds: 0.4, gain_db: -9 },
  ],
};

describe("audio section normalization", () => {
  it("rounds like the server and orders cues by time", () => {
    const n = normalizeAudio(full)!;
    assert.equal(n.source_gain_db, -1.5);
    assert.equal(n.music!.gain_db, -18);
    assert.equal(n.music!.source_start_seconds, 12.5);
    assert.deepEqual(
      n.sfx.map((c) => [c.asset_id, c.at_seconds]),
      [["a", 0.4], ["b", 3.21]],
    );
  });

  it("treats a section that changes nothing as no section", () => {
    assert.equal(normalizeAudio({ source_gain_db: 0, normalize: false, music: null, sfx: [] }), null);
    assert.notEqual(normalizeAudio({ source_gain_db: 0, normalize: true, music: null, sfx: [] }), null);
    assert.equal(normalizeAudio(null), null);
  });

  it("reads a stored configuration back and matches equivalent settings", () => {
    const stored = { audio: { version: "audio_mix_v1", loudness: "social_v1", ...normalizeAudio(full) } };
    assert.ok(sameAudio(audioFromConfiguration(stored), full));
    assert.ok(!sameAudio(audioFromConfiguration(stored), { ...full, normalize: false }));
    assert.equal(audioFromConfiguration({}), null);
  });

  it("summarizes for version names", () => {
    assert.equal(audioSummary(full), "Music · 2 sound effects");
    assert.equal(audioSummary({ ...full, music: null, sfx: full.sfx.slice(0, 1) }), "1 sound effect");
    assert.equal(audioSummary({ source_gain_db: -3, normalize: false, music: null, sfx: [] }), "Original audio −3 dB");
    assert.equal(audioSummary(null), null);
  });
});

describe("music timing shared with the renderer", () => {
  it("plays from the chosen point, then loops from the start", () => {
    const m = { ...music, source_start_seconds: 12, fade_in_seconds: 0, fade_out_seconds: 0 };
    assert.equal(musicPositionAt(1, m, 15, 20), 13);
    assert.equal(musicPositionAt(4, m, 15, 20), 1); // 12 + 4 = 16 → 1 s into the second pass
    assert.equal(musicPositionAt(19, m, 15, 20), 1); // 3 s first pass + 15 s loop → 1 s
    const noLoop = { ...m, loop: false };
    assert.equal(musicTimeline(noLoop, 15, 20).plays, 3);
    assert.equal(musicPositionAt(4, noLoop, 15, 20), null);
  });

  it("keeps fades inside the music that plays and applies the gain", () => {
    const short = { ...music, loop: false, fade_in_seconds: 4, fade_out_seconds: 4, gain_db: 0 };
    const t = musicTimeline(short, 3, 10);
    assert.deepEqual([t.plays, t.fadeIn, t.fadeOut], [3, 1.5, 1.5]);
    assert.equal(musicLevelAt(0, short, 3, 10), 0);
    assert.equal(musicLevelAt(1.5, short, 3, 10), 1);
    assert.equal(musicLevelAt(5, short, 3, 10), 0);
    const quiet = { ...music, gain_db: -20, fade_in_seconds: 0, fade_out_seconds: 0 };
    assert.ok(Math.abs(musicLevelAt(2, quiet, 60, 10) - 0.1) < 1e-9);
  });
});

describe("sound-effect cues in the preview", () => {
  const cues = [{ at_seconds: 1 }, { at_seconds: 2.5 }, { at_seconds: 2.5 }];
  it("fire once when forward playback crosses them", () => {
    assert.deepEqual(crossedCues(cues, 0.9, 1.05), [cues[0]]);
    assert.deepEqual(crossedCues(cues, 1.05, 1.3), []);
    assert.equal(crossedCues(cues, 2.4, 2.6).length, 2);
  });

  it("never fire on a seek, backwards or a jump", () => {
    assert.deepEqual(crossedCues(cues, 3, 0.5), []);
    assert.deepEqual(crossedCues(cues, 0, 3), []);
    assert.deepEqual(crossedCues(cues, 1, 1), []);
  });
});
