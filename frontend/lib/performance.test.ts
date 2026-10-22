// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  accessState,
  analyticsOutcome,
  baselineText,
  confidenceText,
  insightsEmptyText,
  positionText,
  windowSummary,
  metric,
  niceMax,
  percent,
  reportingDay,
  seriesOf,
  syncLabel,
  type AnalyticsAccess,
  type DailyMetric,
  type Insights,
} from "./performance-rules.ts";

const access = (overrides: Partial<AnalyticsAccess> = {}): AnalyticsAccess => ({
  enabled: true, connected: true, connection_status: "connected", analytics_access: true,
  simulated: false, ...overrides,
});

describe("access states", () => {
  it("are resolved in order", () => {
    assert.equal(accessState(access({ enabled: false, connected: false })), "disabled");
    assert.equal(accessState(access({ connected: false, connection_status: null })), "not_connected");
    assert.equal(accessState(access({ connection_status: "needs_reconnect" })), "reconnect");
    assert.equal(accessState(access({ analytics_access: false })), "upgrade");
    assert.equal(accessState(access()), "ready");
  });
});

describe("honest numbers", () => {
  it("never shows a missing figure as zero", () => {
    assert.equal(metric(null), "—");
    assert.equal(metric(undefined), "—");
    assert.equal(metric(0), "0");
    assert.equal(percent(null), "—");
    assert.equal(percent(131.66), "131.7%");
  });
  it("compacts large figures", () => {
    assert.equal(metric(9_999), "9,999");
    assert.equal(metric(12_900), "12.9K");
  });
  it("keeps reporting days as calendar days", () => {
    assert.equal(reportingDay("2026-10-20"), "Oct 20");
  });
  it("keeps gaps in series", () => {
    const day = (date: string, engaged: number | null) =>
      ({ date, engaged_views: engaged, average_view_percentage: null }) as DailyMetric;
    assert.deepEqual(seriesOf([day("2026-10-01", 4), day("2026-10-02", null)], "engaged_views"), [
      { date: "2026-10-01", value: 4 }, { date: "2026-10-02", value: null },
    ]);
  });
  it("picks clean axis tops", () => {
    assert.equal(niceMax([null, 0]), 1);
    assert.equal(niceMax([7]), 10);
    assert.equal(niceMax([180]), 200);
    assert.equal(niceMax([2400, 30]), 2500);
    assert.equal(niceMax([101]), 200);
  });
});

describe("sync and OAuth outcomes", () => {
  it("labels refreshing and failures with the server's safe message", () => {
    const sync = { kind: "manual", error_code: null, error_message: null, created_at: "", completed_at: null };
    assert.equal(syncLabel(null), null);
    assert.equal(syncLabel({ ...sync, status: "queued" }), "Refreshing…");
    assert.equal(syncLabel({ ...sync, status: "completed" }), null);
    assert.equal(syncLabel({ ...sync, status: "failed", error_message: "Analytics access is not connected" }),
      "Analytics access is not connected");
  });
  it("explains each analytics outcome and says publishing is untouched", () => {
    assert.equal(analyticsOutcome(new URLSearchParams("youtube=connected")), null);
    assert.equal(analyticsOutcome(new URLSearchParams("analytics=connected"))?.ok, true);
    const partial = analyticsOutcome(new URLSearchParams("analytics=error&reason=analytics_not_granted"));
    assert.equal(partial?.ok, false);
    assert.match(partial?.message ?? "", /publishing keeps working/);
    assert.match(analyticsOutcome(new URLSearchParams("analytics=error&reason=???"))?.message ?? "", /not connected/);
  });
});

describe("windows and baselines", () => {
  const w = { key: "day_7", days_expected: 7, days_reported: 4, engaged_views: null, views: null,
    average_view_percentage: null, watch_time_seconds: null, likes: null, comments: null,
    subscribers_gained: null } as const;
  it("explains open and incomplete windows instead of showing zero", () => {
    assert.equal(windowSummary(undefined), "Not synced yet");
    assert.match(windowSummary({ ...w, status: "open" }), /4 of 7 days/);
    assert.match(windowSummary({ ...w, status: "incomplete" }), /not compared/);
    assert.equal(windowSummary({ ...w, status: "complete", engaged_views: 1200 }), "1,200 engaged views");
  });
  it("words positions observationally", () => {
    const p = { metric: "engaged_views", window: "day_7", value: 300, median: 100 } as const;
    assert.equal(positionText({ ...p, ratio: 3, label: "above" }), "above your usual (3.0× your median)");
    assert.equal(positionText({ ...p, ratio: null, label: "above" }), "above your usual");
  });
  it("says when there is no reliable pattern yet", () => {
    const b = { metric: "engaged_views", window: "day_7", minimum_sample: 5 } as const;
    assert.match(baselineText({ ...b, sample_size: 3, median: 10, reliable: false }), /No reliable pattern yet: 3 of 5/);
    assert.match(baselineText({ ...b, sample_size: 6, median: 1500, reliable: true }), /1,500 engaged views .* 6 comparable/);
    for (const text of [baselineText(undefined), positionText({ metric: "engaged_views", window: "", value: 1, median: 1, ratio: 1, label: "near" })]) {
      assert.doesNotMatch(text, /viral|best|guarantee|will /i);
    }
  });
});

describe("insights copy", () => {
  const data: Insights = { status: "insufficient", source: "youtube", simulated: false, engine_version: "insights_v1",
    computed_at: "", sample_size: 4, minimum_sample: 10, minimum_group: 5, insights: [] };
  it("never invents a pattern", () => {
    assert.match(insightsEmptyText(data), /No reliable pattern yet: 4 of 10/);
    assert.match(insightsEmptyText({ ...data, status: "ready", sample_size: 14 }), /No clear pattern .* 14 comparable/);
  });
  it("states the evidence behind each insight", () => {
    const insight = { group_size: 6, comparison_size: 7, confidence: "limited" } as Parameters<typeof confidenceText>[0];
    assert.equal(confidenceText(insight), "Limited evidence · 6 vs 7 shorts");
    assert.equal(confidenceText({ ...insight, confidence: "moderate" }), "Moderate confidence · 6 vs 7 shorts");
  });
});
