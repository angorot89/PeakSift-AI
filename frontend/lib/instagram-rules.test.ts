import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { captionCounts, instagramOutcome, instagramProblems, instagramStage, isMetaConsentUrl } from "./instagram-rules.ts";

describe("instagram reels", () => {
  it("checks the caption against Instagram's limits", () => {
    assert.deepEqual(instagramProblems("How I priced it #creator", 30), {});
    assert.match(instagramProblems("x".repeat(2201), 30).caption!, /2200/);
    assert.match(instagramProblems("#a ".repeat(31), 30).caption!, /30 hashtags/);
    assert.match(instagramProblems("@a ".repeat(21), 30).caption!, /20 mentions/);
  });

  it("checks the length of the Short", () => {
    assert.match(instagramProblems("", 2).duration!, /3 seconds and 15 minutes/);
    assert.match(instagramProblems("", 901).duration!, /15 minutes/);
    assert.equal(instagramProblems("", null).duration, undefined);
  });

  it("counts hashtags and mentions", () => {
    assert.equal(captionCounts("plain"), "");
    assert.equal(captionCounts("#a #b @c"), "2 hashtags · 1 mention");
  });

  it("accepts only Meta's consent screen", () => {
    assert.equal(isMetaConsentUrl("https://www.facebook.com/v27.0/dialog/oauth?client_id=1"), true);
    assert.equal(isMetaConsentUrl("https://www.facebook.com.evil.example/v27.0/dialog/oauth"), false);
    assert.equal(isMetaConsentUrl("https://www.facebook.com/login"), false);
    assert.equal(isMetaConsentUrl("http://www.facebook.com/v27.0/dialog/oauth"), false);
  });

  it("explains how the connection ended", () => {
    assert.equal(instagramOutcome(new URLSearchParams("")), null);
    assert.equal(instagramOutcome(new URLSearchParams("instagram=connected"))!.ok, true);
    assert.match(instagramOutcome(new URLSearchParams("instagram=error&reason=no_instagram_account"))!.message, /professional account/);
  });

  it("never says posted before it is", () => {
    const job = { status: "processing", progress_percent: 100, is_stale: false, simulated: false };
    assert.match(instagramStage(job).label, /then PeakSift posts it/);
    assert.equal(instagramStage({ ...job, status: "published" }).label, "Posted on Instagram");
    assert.equal(instagramStage({ ...job, status: "provider_failed" }).tone, "attention");
  });
});
