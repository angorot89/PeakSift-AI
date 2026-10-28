// The command menu (Cmd/Ctrl+K): which commands exist where, how a query filters them, and when
// typing becomes a question for Ask PeakSift. Pure functions (unit-tested); the dialog lives in
// components/app/command-menu.tsx.

import { type CopilotPage, QUESTION_MAX, starters } from "./copilot-rules.ts";
import { GLOBAL_NAV, PROJECT_SECTIONS, type ProjectSection, projectHref, SETTINGS_NAV } from "./navigation.ts";

export type CommandGroup = "Next step" | "This project" | "Go to" | "Projects" | "Ask PeakSift";

export type Command = {
  id: string;
  group: CommandGroup;
  label: string;
  /** A muted second line (the project, what a step is about). */
  hint?: string;
  /** Extra words it is found by (never shown). */
  keywords?: string;
  run: { kind: "navigate"; href: string } | { kind: "ask"; question: string };
};

export type CommandSource = {
  page: CopilotPage;
  /** The project the creator is in, if any. */
  project: { id: string; name: string } | null;
  /** The creator's projects, most recent first. */
  projects: { id: string; name: string }[];
  /** The server's next best step (the project's, or the workspace's first). */
  next: { title: string; cta: string | null; href: string; projectName?: string } | null;
};

/** Projects listed before anything is typed (all of them are searchable). */
export const RECENT_PROJECTS = 5;

const SECTION_WORDS: Partial<Record<ProjectSection, string>> = {
  clips: "moments shorts",
  assets: "visuals b-roll images library",
  source: "video transcript upload",
};

/** Every command for where the creator is, in display order. */
export function buildCommands(source: CommandSource): Command[] {
  const commands: Command[] = [];
  const { next, project } = source;
  if (next?.cta) {
    commands.push({
      id: "next",
      group: "Next step",
      label: next.cta,
      hint: next.projectName ? `${next.projectName} · ${next.title}` : next.title,
      keywords: "next continue",
      run: { kind: "navigate", href: next.href },
    });
  }
  if (project) {
    for (const section of PROJECT_SECTIONS) {
      commands.push({
        id: `section:${section.key}`,
        group: "This project",
        label: section.label,
        hint: project.name,
        keywords: SECTION_WORDS[section.key],
        run: { kind: "navigate", href: projectHref(project.id, section.key) },
      });
    }
  }
  for (const item of [...GLOBAL_NAV, SETTINGS_NAV]) {
    commands.push({ id: `go:${item.key}`, group: "Go to", label: item.label, run: { kind: "navigate", href: item.href } });
  }
  commands.push({
    id: "go:new",
    group: "Go to",
    label: "New project",
    keywords: "create upload add",
    run: { kind: "navigate", href: "/projects/new" },
  });
  for (const item of source.projects) {
    if (item.id === project?.id) continue;
    commands.push({
      id: `project:${item.id}`,
      group: "Projects",
      label: item.name,
      keywords: "project open",
      run: { kind: "navigate", href: projectHref(item.id) },
    });
  }
  for (const question of starters(source.page)) {
    commands.push({ id: `ask:${question}`, group: "Ask PeakSift", label: question, run: { kind: "ask", question } });
  }
  return commands;
}

const QUESTION_START =
  /^(what|whats|what's|how|why|which|who|when|where|should|can|could|do|does|did|is|are|give|show|suggest|find|help|tell|explain|quel|quelle|quels|quelles|comment|pourquoi|est-ce|peux|donne)\b/i;

/** Whether a query reads as a question for Ask PeakSift rather than a place to go. */
export function looksLikeQuestion(query: string): boolean {
  const text = query.trim();
  return /[?？؟]$/.test(text) || text.split(/\s+/).length >= 4 || QUESTION_START.test(text);
}

function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

function rank(command: Command, query: string, words: string[]): number | null {
  const label = fold(command.label);
  const rest = fold(`${command.hint ?? ""} ${command.keywords ?? ""} ${command.group}`);
  if (!words.every((word) => label.includes(word) || rest.includes(word))) return null;
  if (label.startsWith(query)) return 0;
  if (label.split(/[\s—–·:-]+/).some((part) => part.startsWith(words[0]))) return 1;
  if (label.includes(query)) return 2;
  return 3;
}

/**
 * What the menu lists for a query. Nothing typed: the commands as built, projects trimmed to the
 * most recent. Typed: matching commands, best first, plus "Ask PeakSift" with the query — first
 * when it reads as a question or nothing else matches, otherwise last.
 */
export function filterCommands(commands: Command[], query: string): Command[] {
  const text = query.trim().slice(0, QUESTION_MAX);
  if (!text) {
    let projects = 0;
    return commands.filter((command) => command.group !== "Projects" || ++projects <= RECENT_PROJECTS);
  }
  const folded = fold(text);
  const words = folded.split(/\s+/).filter(Boolean);
  const matches = commands
    .map((command, index) => ({ command, index, score: rank(command, folded, words) }))
    .filter((entry): entry is { command: Command; index: number; score: number } => entry.score !== null)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((entry) => entry.command)
    // a suggested question typed out in full is the typed question
    .filter((command) => !(command.run.kind === "ask" && fold(command.run.question) === folded));
  const ask: Command = { id: "ask:typed", group: "Ask PeakSift", label: text, run: { kind: "ask", question: text } };
  return looksLikeQuestion(text) || matches.length === 0 ? [ask, ...matches] : [...matches, ask];
}

/** The commands by group, groups in order of their first command (order within kept). */
export function groupCommands(commands: Command[]): { group: CommandGroup; commands: Command[] }[] {
  const groups: { group: CommandGroup; commands: Command[] }[] = [];
  for (const command of commands) {
    const entry = groups.find((item) => item.group === command.group);
    if (entry) entry.commands.push(command);
    else groups.push({ group: command.group, commands: [command] });
  }
  return groups;
}

/** Cmd+K on a Mac, Ctrl+K elsewhere (on a Mac, Ctrl+K stays the text fields' "delete to end of line"). */
export function isCommandShortcut(
  event: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean },
  mac: boolean,
): boolean {
  if (event.key.toLowerCase() !== "k" || event.altKey || event.shiftKey) return false;
  return mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey;
}

export function shortcutLabel(mac: boolean): string {
  return mac ? "⌘K" : "Ctrl K";
}
