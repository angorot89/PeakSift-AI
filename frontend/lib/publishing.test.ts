// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  bytes,
  characters,
  connectionOutcome,
  safeReturnPath,
  isActive,
  isGoogleConsentUrl,
  metadataProblems,
  parseTags,
  stageLabel,
  tagsLength,
  type PublishJob,
  type PublishMetadata,
} from "./publishing-rules.ts";

const meta = (overrides: Partial<PublishMetadata> = {}): PublishMetadata => ({
  title: "That was crazy",
  description: "",
  tags: [],
  privacy: "private",
  made_for_kids: false,
  ...overrides,
});

describe("YouTube metadata rules (mirrors the API)", () => {
  it("counts characters and bytes the way the server does", () => {
    assert.equal(characters("🎬é"), 2);
    assert.equal(bytes("é"), 2);
  });

  it("accepts the limits and refuses one past them", () => {
    assert.deepEqual(metadataProblems(meta({ title: "x".repeat(100) })), {});
    assert.match(metadataProblems(meta({ title: "x".repeat(101) })).title ?? "", /101 \/ 100/);
    assert.deepEqual(metadataProblems(meta({ description: "é".repeat(2500) })), {});
    assert.match(metadataProblems(meta({ description: "é".repeat(2501) })).description ?? "", /5002 \/ 5000 bytes/);
  });

  it("refuses empty titles, angle brackets and duplicate tags", () => {
    assert.equal(metadataProblems(meta({ title: "  " })).title, "Add a title");
    assert.match(metadataProblems(meta({ title: "<b>" })).title ?? "", /< or >/);
    assert.match(metadataProblems(meta({ tags: ["One", "one"] })).tags ?? "", /only once/);
  });

  it("parses comma-separated tags and counts them like YouTube", () => {
    assert.deepEqual(parseTags(" a, two words ,, b "), ["a", "two words", "b"]);
    assert.equal(tagsLength(["one", "two words"]), 3 + 11 + 1);
    assert.equal(tagsLength([]), 0);
    assert.match(metadataProblems(meta({ tags: ["x".repeat(499), "y"] })).tags ?? "", /501 \/ 500/);
  });
});

const job = (overrides: Partial<PublishJob>): PublishJob => ({
  ...meta(),
  id: "j",
  edit_id: "e",
  provider: "youtube",
  status: "queued",
  progress_percent: 0,
  bytes_uploaded: 0,
  bytes_total: null,
  video_url: null,
  studio_url: null,
  simulated: false,
  error_code: null,
  error_message: null,
  retryable: false,
  is_stale: false,
  awaiting_processing: false,
  attempt: 1,
  created_at: "2026-10-17T00:00:00Z",
  started_at: null,
  completed_at: null,
  published_at: null,
  ...overrides,
});

describe("job stages", () => {
  it("labels real progress and never claims more than happened", () => {
    assert.equal(stageLabel(job({ status: "uploading", progress_percent: 42 })), "Uploading to YouTube · 42%");
    assert.equal(stageLabel(job({ status: "uploaded" })), "Uploaded to YouTube");
    assert.equal(stageLabel(job({ status: "uploaded", simulated: true })), "Uploaded (simulated)");
    assert.equal(stageLabel(job({ status: "uploading", is_stale: true })), "Stalled");
    assert.equal(stageLabel(job({ status: "uploaded", awaiting_processing: true })), "Uploaded · checking processing");
  });

  it("polls only while the upload is genuinely running", () => {
    assert.equal(isActive(job({ status: "uploading" })), true);
    assert.equal(isActive(job({ status: "uploading", is_stale: true })), false);
    assert.equal(isActive(job({ status: "uploaded" })), false);
    assert.equal(isActive(job({ status: "failed" })), false);
  });
});

describe("connecting", () => {
  it("navigates only to Google's consent page", () => {
    assert.equal(isGoogleConsentUrl("https://accounts.google.com/o/oauth2/auth?x=1"), true);
    assert.equal(isGoogleConsentUrl("https://evil.example/accounts.google.com"), false);
    assert.equal(isGoogleConsentUrl("http://accounts.google.com/"), false);
    assert.equal(isGoogleConsentUrl("javascript:alert(1)"), false);
  });

  it("explains every callback outcome", () => {
    assert.deepEqual(connectionOutcome(new URLSearchParams("youtube=connected")), {
      ok: true,
      message: "Your YouTube account is connected.",
    });
    for (const reason of ["denied", "invalid_state", "expired", "signin_required", "missing_refresh_token", "insufficient_scope", "exchange_failed", "disabled", "unknown"]) {
      const outcome = connectionOutcome(new URLSearchParams(`youtube=error&reason=${reason}`));
      assert.equal(outcome?.ok, false);
      assert.ok(outcome?.message);
    }
    assert.equal(connectionOutcome(new URLSearchParams("")), null);
  });
});

describe("coming back after connecting", () => {
  const ID = "3f1c0a1e-0000-4000-8000-000000000001";
  it("returns only to a Short or an editor of this app", () => {
    assert.equal(safeReturnPath(`/shorts/${ID}`), `/shorts/${ID}`);
    assert.equal(safeReturnPath("/shorts/review"), "/shorts/review");
    assert.equal(safeReturnPath("/shorts/review?x=//evil.example"), null);
    assert.equal(safeReturnPath(`/projects/${ID}/clips/${ID}?edit=${ID}`), `/projects/${ID}/clips/${ID}?edit=${ID}`);
    assert.equal(safeReturnPath(`/projects/${ID}/clips/${ID}`), `/projects/${ID}/clips/${ID}`);
  });
  it("drops anything else", () => {
    for (const path of ["https://evil.example/shorts/x", "//evil.example", `/shorts/${ID}/../../settings`, "/shorts/not-an-id", `/shorts/${ID}?next=https://evil.example`, "", null]) {
      assert.equal(safeReturnPath(path), null, String(path));
    }
  });
});
