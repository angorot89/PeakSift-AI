import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { LibraryItem } from "./library.ts";
import { categoriesOf, categoryLabel, filterLibrary, lengthLabel } from "./library-rules.ts";

const item = (id: string, kind: LibraryItem["kind"], title: string, category: string, tags: string[] = []): LibraryItem => ({
  id, kind, title, category, tags, duration_seconds: 1, licence: "CC0", credit: "Kenney", source_name: "Kenney", source_url: "https://kenney.nl",
});
const ITEMS = [
  item("whoosh-1", "sfx", "Whoosh 1", "transitions", ["whoosh", "rush"]),
  item("punch-1", "sfx", "Punch 1", "hits", ["punch"]),
  item("bossa", "music", "8-bit Bossa", "chill", ["retro"]),
  item("fire", "sticker", "Fire", "emoji", ["fire"]),
];

describe("library browser", () => {
  it("filters by kind, words and category", () => {
    assert.deepEqual(filterLibrary(ITEMS, "sfx", "", null).map((i) => i.id), ["whoosh-1", "punch-1"]);
    assert.deepEqual(filterLibrary(ITEMS, "sfx", "rush", null).map((i) => i.id), ["whoosh-1"]);
    assert.deepEqual(filterLibrary(ITEMS, "sfx", "booms", null).map((i) => i.id), ["punch-1"]); // the category's words
    assert.deepEqual(filterLibrary(ITEMS, "sfx", "", "hits").map((i) => i.id), ["punch-1"]);
    assert.deepEqual(filterLibrary(ITEMS, "music", "BOSSA", null).map((i) => i.id), ["bossa"]);
    assert.deepEqual(filterLibrary(ITEMS, "sticker", "fire water", null), []);
  });

  it("lists categories and words them", () => {
    assert.deepEqual(categoriesOf(ITEMS, "sfx"), ["transitions", "hits"]);
    assert.equal(categoryLabel("interface"), "Clicks & pops");
    assert.equal(categoryLabel("new_one"), "New_one");
    assert.equal(lengthLabel(0.62), "0.6 s");
    assert.equal(lengthLabel(84.6), "1:25");
    assert.equal(lengthLabel(null), "");
  });
});
