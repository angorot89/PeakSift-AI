import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { toolFromParam, toolMarks } from "./editor-tools.ts";

describe("editor tools", () => {
  it("opens the tool a link names, including Auto Edit's section names", () => {
    assert.equal(toolFromParam(null), "style");
    assert.equal(toolFromParam("captions"), "captions");
    assert.equal(toolFromParam("layout"), "style");
    assert.equal(toolFromParam("hook"), "opening");
    assert.equal(toolFromParam("audio"), "sound");
    assert.equal(toolFromParam("visuals"), "visuals");
    assert.equal(toolFromParam("brand"), "brand");
    assert.equal(toolFromParam("<script>"), "style");
  });

  it("marks what blocks rendering before what is merely in use", () => {
    const idle = { awaitingAnalysis: false, awaitingWords: false, hookOn: false, hookInvalid: false, visuals: 0, visualsInvalid: false, audioActive: false, branded: false };
    assert.deepEqual(toolMarks(idle), { style: null, captions: null, opening: null, visuals: null, sound: null, brand: null });
    const busy = toolMarks({ ...idle, awaitingWords: true, hookOn: true, hookInvalid: true, visuals: 2, audioActive: true, branded: true });
    assert.equal(busy.captions, "attention");
    assert.equal(busy.opening, "attention");
    assert.equal(busy.visuals, "on");
    assert.equal(busy.sound, "on");
    assert.equal(busy.brand, "on");
  });
});
