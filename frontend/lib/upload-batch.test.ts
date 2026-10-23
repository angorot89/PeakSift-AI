import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { batchSummary } from "./upload-batch.ts";

describe("upload batches", () => {
  it("reports one progress for the whole batch, weighted by size", () => {
    const summary = batchSummary([
      { size: 300, state: "uploading", progress: 50 },
      { size: 100, state: "processing", progress: 100 },
    ]);
    assert.equal(summary.working, true);
    assert.equal(summary.percent, 63); // (150 + 100) / 400
    assert.equal(summary.label, "Adding 2 files · 0 of 2 done");
  });

  it("leaves failed files out of the progress and says how many were added", () => {
    const summary = batchSummary([
      { size: 100, state: "done", progress: 100 },
      { size: 100, state: "existing", progress: 100 },
      { size: 999, state: "failed", progress: 10 },
    ]);
    assert.equal(summary.working, false);
    assert.equal(summary.percent, 100);
    assert.equal(summary.label, "2 files added · 1 couldn't be added");
  });

  it("mentions files that were already in the project", () => {
    assert.equal(batchSummary([{ size: 5, state: "existing", progress: 100 }]).label, "1 file added (1 already in this project)");
    assert.equal(batchSummary([{ size: 5, state: "failed", progress: 0 }]).label, "1 couldn't be added");
  });
});
