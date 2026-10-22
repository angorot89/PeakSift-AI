// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  accessState,
  analyticsOutcome,
  metric,
  niceMax,
  percent,
  reportingDay,
  seriesOf,
  syncLabel,
  type AnalyticsAccess,
  type DailyMetric,
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
