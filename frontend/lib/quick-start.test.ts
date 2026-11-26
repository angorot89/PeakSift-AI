import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { QUICK_START_FALLBACK_NAME, nameFromFile, quickStartNotice } from "./quick-start.ts";

describe("quick start project name", () => {
  it("turns a file name into readable words", () => {
    assert.equal(nameFromFile("Friday_stream-2026.09.28.mp4"), "Friday stream 2026 09 28");
    assert.equal(nameFromFile("podcast ep 12.mov"), "podcast ep 12");
    assert.equal(nameFromFile("حلقة_جديدة.mp4"), "حلقة جديدة");
  });

  it("never keeps a path", () => {
    assert.equal(nameFromFile("C:\\Users\\me\\Videos\\vlog.final.webm"), "vlog final");
    assert.equal(nameFromFile("../../etc/passwd.mp4"), "passwd");
  });

  it("falls back when nothing readable is left", () => {
    assert.equal(nameFromFile("___.mp4"), QUICK_START_FALLBACK_NAME);
    assert.equal(nameFromFile(""), QUICK_START_FALLBACK_NAME);
    assert.equal(nameFromFile(".mp4"), "mp4");
  });

  it("is bounded", () => {
    assert.equal(nameFromFile(`${"a".repeat(500)}.mp4`).length, 200);
  });
});

describe("quick start notice", () => {
  it("says nothing when everything started", () => {
    assert.equal(quickStartNotice({ video_status: "ready", transcription_started: true }), null);
  });

  it("explains an unreadable file and a job that did not start", () => {
    assert.match(quickStartNotice({ video_status: "failed", transcription_started: false })!, /couldn't be read/);
    assert.match(quickStartNotice({ video_status: "ready", transcription_started: false })!, /Start the transcription/);
  });
});
