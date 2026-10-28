// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  buildCommands,
  type CommandSource,
  filterCommands,
  groupCommands,
  isCommandShortcut,
  looksLikeQuestion,
  RECENT_PROJECTS,
  shortcutLabel,
} from "./command-menu.ts";

const P1 = "11111111-1111-4111-8111-111111111111";
const projects = Array.from({ length: 8 }, (_, i) => ({ id: `${i}0000000-0000-4000-8000-000000000000`, name: `Project ${i}` }));
const inProject: CommandSource = {
  page: "overview",
  project: { id: P1, name: "Bridge Lab — Épisode 4" },
  projects: [{ id: P1, name: "Bridge Lab — Épisode 4" }, ...projects],
  next: { title: "Your Short is ready", cta: "Open the Short", href: `/projects/${P1}/clips/c?edit=e` },
};

describe("command menu commands", () => {
  it("lists the next step, the project's sections, destinations, other projects and suggested questions", () => {
    const commands = buildCommands(inProject);
    assert.equal(commands[0].group, "Next step");
    assert.equal(commands[0].label, "Open the Short");
    assert.deepEqual(commands[0].run, { kind: "navigate", href: `/projects/${P1}/clips/c?edit=e` });
    const sections = commands.filter((c) => c.group === "This project");
    assert.deepEqual(sections.map((c) => c.label), ["Overview", "Source", "Clips", "Assets", "Analytics"]);
    assert.deepEqual(sections[3].run, { kind: "navigate", href: `/projects/${P1}/assets` });
    assert.deepEqual(
      commands.filter((c) => c.group === "Go to").map((c) => c.label),
      ["Home", "Projects", "Analytics", "Brand Studio", "Settings", "New project"],
    );
    // the current project is not offered as a place to go
    assert.ok(!commands.some((c) => c.group === "Projects" && c.label.startsWith("Bridge")));
    const asks = commands.filter((c) => c.group === "Ask PeakSift");
    assert.deepEqual(asks.map((c) => c.run), [
      { kind: "ask", question: "What should I do next?" },
      { kind: "ask", question: "Give me 3 Short ideas from this video" },
    ]);
  });

  it("has no next step while PeakSift is working, and no project section outside a project", () => {
    const commands = buildCommands({ page: "home", project: null, projects: [], next: { title: "Finding moments", cta: null, href: "/x" } });
    assert.ok(!commands.some((c) => c.group === "Next step" || c.group === "This project" || c.group === "Projects"));
    assert.ok(commands.some((c) => c.label === "What should I work on next?"));
  });

  it("suggests getting-started questions for a project without a video", () => {
    const asks = buildCommands({ ...inProject, hasSource: false }).filter((c) => c.group === "Ask PeakSift");
    assert.deepEqual(asks.map((c) => c.label), ["What should I do next?", "What kind of video works best to start with?"]);
  });

  it("names the project of a workspace step", () => {
    const [step] = buildCommands({ page: "home", project: null, projects: [], next: { title: "Pick a moment", cta: "Review moments", href: "/p", projectName: "Podcast" } });
    assert.equal(step.hint, "Podcast · Pick a moment");
  });
});

describe("command menu filtering", () => {
  const commands = buildCommands(inProject);

  it("lists everything with nothing typed, trimming projects to the most recent", () => {
    const shown = filterCommands(commands, "  ");
    assert.equal(shown.filter((c) => c.group === "Projects").length, RECENT_PROJECTS);
    assert.equal(shown.length, commands.length - (projects.length - RECENT_PROJECTS));
  });

  it("finds destinations by name, by keyword and without accents, best first, then offers the question", () => {
    const assets = filterCommands(commands, "ass");
    assert.equal(assets[0].label, "Assets");
    assert.equal(assets.at(-1)?.run.kind, "ask");
    assert.equal(filterCommands(commands, "b-roll")[0].label, "Assets");
    assert.equal(filterCommands(commands, "moments")[0].label, "Clips");
    assert.equal(filterCommands(commands, "project 7")[0].label, "Project 7");
    assert.equal(filterCommands(commands, "episode")[0].hint, "Bridge Lab — Épisode 4");
  });

  it("asks PeakSift first when the query reads as a question or nothing matches", () => {
    const question = filterCommands(commands, "Which moment should I use?");
    assert.deepEqual(question[0].run, { kind: "ask", question: "Which moment should I use?" });
    const nothing = filterCommands(commands, "zzzz");
    assert.equal(nothing.length, 1);
    assert.deepEqual(nothing[0].run, { kind: "ask", question: "zzzz" });
  });

  it("does not repeat a suggested question typed in full", () => {
    const shown = filterCommands(commands, "what should i do next?");
    assert.equal(shown.filter((c) => c.run.kind === "ask").length, 1);
    assert.equal(shown[0].id, "ask:typed");
  });

  it("keeps questions within the Copilot's length limit", () => {
    const [ask] = filterCommands(commands, `why ${"x".repeat(1200)}`);
    assert.equal(ask.label.length, 1000);
    const [emoji] = filterCommands(commands, `why ${"🎬".repeat(1200)}`);
    assert.equal([...emoji.label].length, 1000); // never a broken half emoji
  });

  it("groups in order of first appearance", () => {
    const groups = groupCommands(filterCommands(commands, "ana"));
    assert.deepEqual(groups.map((g) => g.group), ["This project", "Go to", "Ask PeakSift"]);
  });
});

describe("command menu questions and shortcut", () => {
  it("recognises questions in several languages and lengths", () => {
    for (const text of ["how is my short doing", "Quelle vidéo choisir", "我该做什么？", "ما الذي يجب أن أفعله؟", "best moment for a short"]) {
      assert.ok(looksLikeQuestion(text), text);
    }
    for (const text of ["assets", "home", "bridge lab"]) assert.ok(!looksLikeQuestion(text), text);
  });

  it("opens with Cmd+K on a Mac and Ctrl+K elsewhere, nothing else", () => {
    const key = (k: string, mods: Partial<Record<"metaKey" | "ctrlKey" | "altKey" | "shiftKey", boolean>> = {}) => ({
      key: k, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...mods,
    });
    assert.ok(isCommandShortcut(key("k", { metaKey: true }), true));
    assert.ok(isCommandShortcut(key("K", { ctrlKey: true }), false));
    assert.ok(!isCommandShortcut(key("k", { ctrlKey: true }), true)); // Mac text editing
    assert.ok(!isCommandShortcut(key("k", { metaKey: true }), false));
    assert.ok(!isCommandShortcut(key("k", { metaKey: true, shiftKey: true }), true));
    assert.ok(!isCommandShortcut(key("j", { metaKey: true }), true));
    assert.ok(!isCommandShortcut(key("k"), true));
    assert.equal(shortcutLabel(true), "⌘K");
    assert.equal(shortcutLabel(false), "Ctrl K");
  });
});
