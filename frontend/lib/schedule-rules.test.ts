import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  addDays,
  dayKey,
  fromLocalInput,
  groupByDay,
  postState,
  suggestedTime,
  timeProblem,
  toLocalInput,
  weekDays,
  weekLabel,
  weekStart,
} from "./schedule-rules.ts";

describe("the calendar week", () => {
  it("starts on Monday at local midnight", () => {
    const thursday = new Date(2026, 10, 26, 15, 30);
    assert.equal(dayKey(weekStart(thursday)), "2026-11-23");
    assert.equal(dayKey(weekStart(new Date(2026, 10, 23, 0, 0))), "2026-11-23"); // a Monday
    assert.equal(dayKey(weekStart(new Date(2026, 10, 29, 23, 59))), "2026-11-23"); // a Sunday
    assert.equal(weekStart(thursday).getHours(), 0);
  });

  it("has seven days and crosses months", () => {
    const days = weekDays(new Date(2026, 10, 30));
    assert.deepEqual(days.map(dayKey), [
      "2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04", "2026-12-05", "2026-12-06",
    ]);
    assert.equal(dayKey(addDays(new Date(2026, 11, 31), 1)), "2027-01-01");
  });

  it("labels the week", () => {
    assert.equal(weekLabel(new Date(2026, 10, 23), "en-US"), "Nov 23 – 29");
    assert.equal(weekLabel(new Date(2026, 10, 30), "en-US"), "Nov 30 – Dec 6");
  });

  it("groups posts by their local day, in time order", () => {
    const at = (day: number, hour: number) => new Date(2026, 10, day, hour).toISOString();
    const days = groupByDay([
      { at: at(27, 19), id: "c" },
      { at: at(26, 9), id: "a" },
      { at: at(27, 7), id: "b" },
    ]);
    assert.deepEqual([...days.keys()], ["2026-11-26", "2026-11-27"]);
    assert.deepEqual(days.get("2026-11-27")!.map((item) => item.id), ["b", "c"]);
  });
});

describe("the creator's local time", () => {
  it("round-trips through a datetime-local value", () => {
    const when = new Date(2026, 10, 27, 19, 30);
    assert.equal(toLocalInput(when), "2026-11-27T19:30");
    assert.equal(fromLocalInput("2026-11-27T19:30")!.getTime(), when.getTime());
    assert.equal(fromLocalInput(""), null);
    assert.equal(fromLocalInput("tomorrow"), null);
  });

  it("suggests the next full hour, at least an hour away", () => {
    const suggestion = suggestedTime(new Date(2026, 10, 26, 20, 41));
    assert.equal(toLocalInput(suggestion), "2026-11-26T22:00");
    assert.ok(suggestion.getTime() - new Date(2026, 10, 26, 20, 41).getTime() >= 60 * 60000);
  });

  it("refuses times that are missing, too soon or too far", () => {
    const now = new Date(2026, 10, 26, 20, 0);
    assert.equal(timeProblem("2026-11-26T22:00", now), null);
    assert.match(timeProblem("", now)!, /Pick a date/);
    assert.match(timeProblem("2026-11-26T20:02", now)!, /few minutes/);
    assert.match(timeProblem("2026-11-25T20:00", now)!, /few minutes/);
    assert.match(timeProblem("2028-01-01T10:00", now)!, /next year/);
  });
});

describe("a post's state on the calendar", () => {
  const job = (status: string, extra = {}) => ({ status, is_stale: false, error_code: null, ...extra });

  it("says what is true and never 'published' early", () => {
    assert.deepEqual(postState(job("scheduled")), { label: "Scheduled", tone: "scheduled" });
    assert.equal(postState(job("uploading")).label, "Publishing");
    assert.equal(postState(job("uploaded")).label, "On YouTube");
    assert.equal(postState(job("published")).label, "Published");
    assert.equal(postState(job("failed")).label, "Not published");
    assert.equal(postState(job("failed", { error_code: "schedule_missed" })).label, "Missed");
    assert.equal(postState(job("provider_failed")).tone, "attention");
    assert.equal(postState(job("uploading", { is_stale: true })).label, "Stalled");
  });
});
