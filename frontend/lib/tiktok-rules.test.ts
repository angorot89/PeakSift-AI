import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  EMPTY_TIKTOK_FORM,
  commercialNotice,
  isTikTokConsentUrl,
  privacyChoices,
  tiktokOptions,
  tiktokOutcome,
  tiktokPrivacyLabel,
  tiktokProblems,
  tiktokStage,
  type TikTokCreator,
  type TikTokForm,
} from "./tiktok-rules.ts";

const creator: TikTokCreator = {
  nickname: "Amine",
  username: "amine",
  privacy_levels: ["PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "SELF_ONLY", "SOMETHING_NEW"],
  comment_disabled: false,
  duet_disabled: false,
  stitch_disabled: true,
  max_duration_seconds: 600,
};
const ready: TikTokForm = { ...EMPTY_TIKTOK_FORM, caption: "Hi", privacy: "FOLLOWER_OF_CREATOR", musicConfirmed: true };

describe("tiktok visibility", () => {
  it("offers only the levels TikTok gave, in words", () => {
    assert.deepEqual(
      privacyChoices(creator, ready).map((choice) => choice.label),
      ["Everyone", "Followers", "Only me"],
    );
    assert.equal(tiktokPrivacyLabel("MUTUAL_FOLLOW_FRIENDS"), "Friends (followers you follow back)");
  });

  it("rules out only-me for branded content", () => {
    const branded = { ...ready, commercial: true, brandedContent: true };
    assert.equal(privacyChoices(creator, branded).find((choice) => choice.value === "SELF_ONLY")!.disabled, true);
    assert.match(tiktokProblems({ ...branded, privacy: "SELF_ONLY" }, creator, 20).privacy!, /only to you/);
  });
});

describe("tiktok post checks", () => {
  it("starts with nothing chosen and says what is missing", () => {
    const problems = tiktokProblems(EMPTY_TIKTOK_FORM, creator, 20);
    assert.match(problems.privacy!, /Choose who can see/);
    assert.match(problems.music!, /music usage/);
    assert.deepEqual(tiktokProblems(ready, creator, 20), {});
  });

  it("checks the caption, the disclosure and the duration", () => {
    assert.match(tiktokProblems({ ...ready, caption: "x".repeat(2201) }, creator, 20).caption!, /2200/);
    assert.match(tiktokProblems({ ...ready, commercial: true }, creator, 20).commercial!, /your brand/);
    assert.match(tiktokProblems(ready, creator, 601).duration!, /600 seconds/);
    assert.match(tiktokProblems({ ...ready, privacy: "MUTUAL_FOLLOW_FRIENDS" }, creator, 20).privacy!, /not available/);
  });

  it("sends what was chosen and never a switch TikTok turned off", () => {
    const form = { ...ready, allowComment: true, allowStitch: true, yourBrand: true };
    assert.deepEqual(tiktokOptions(form, creator), {
      privacy_level: "FOLLOWER_OF_CREATOR",
      allow_comment: true,
      allow_duet: false,
      allow_stitch: false, // off in the creator's TikTok settings
      commercial: false,
      brand_organic: false, // "your brand" only counts with the disclosure on
      brand_content: false,
      music_usage_confirmed: true,
    });
  });

  it("says how TikTok will label a commercial post", () => {
    assert.equal(commercialNotice(ready), null);
    assert.equal(commercialNotice({ commercial: true, yourBrand: false, brandedContent: false }), null);
    assert.match(commercialNotice({ commercial: true, yourBrand: true, brandedContent: false })!, /Promotional content/);
    assert.match(commercialNotice({ commercial: true, yourBrand: true, brandedContent: true })!, /Paid partnership/);
  });
});

describe("tiktok connection and progress", () => {
  it("accepts only TikTok's consent screen", () => {
    assert.equal(isTikTokConsentUrl("https://www.tiktok.com/v2/auth/authorize/?client_key=x"), true);
    assert.equal(isTikTokConsentUrl("https://www.tiktok.com.evil.example/v2/auth/authorize/"), false);
    assert.equal(isTikTokConsentUrl("http://www.tiktok.com/v2/auth/authorize/"), false);
    assert.equal(isTikTokConsentUrl("javascript:alert(1)"), false);
  });

  it("explains how the connection ended", () => {
    assert.equal(tiktokOutcome(new URLSearchParams("")), null);
    assert.equal(tiktokOutcome(new URLSearchParams("tiktok=connected"))!.ok, true);
    assert.match(tiktokOutcome(new URLSearchParams("tiktok=error&reason=denied"))!.message, /declined/);
    assert.match(tiktokOutcome(new URLSearchParams("tiktok=error&reason=zzz"))!.message, /did not complete/);
  });

  it("never says posted before TikTok does", () => {
    const job = { status: "uploaded", progress_percent: 100, is_stale: false, simulated: false };
    assert.match(tiktokStage(job).label, /processing/);
    assert.equal(tiktokStage({ ...job, status: "published" }).label, "Posted on TikTok");
    assert.equal(tiktokStage({ ...job, status: "published", simulated: true }).label, "Posted (simulated)");
    assert.equal(tiktokStage({ ...job, status: "uploading", progress_percent: 40 }).label, "Uploading to TikTok · 40%");
    assert.equal(tiktokStage({ ...job, status: "failed" }).tone, "attention");
    assert.equal(tiktokStage({ ...job, status: "uploading", is_stale: true }).label, "Stalled");
  });
});
