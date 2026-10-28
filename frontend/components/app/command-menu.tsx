"use client";

import { ArrowRight, Compass, Folder, FolderOpen, Search, Sparkles, type LucideIcon } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { useCopilot } from "@/components/app/copilot/copilot-provider";
import { Dialog } from "@/components/ui/dialog";
import { inputClasses } from "@/components/ui/input-styles";
import {
  buildCommands,
  type Command,
  type CommandGroup,
  type CommandSource,
  filterCommands,
  groupCommands,
} from "@/lib/command-menu";
import { copilotScope } from "@/lib/copilot-rules";
import type { Project } from "@/lib/projects";
import { getHome, getProjectSummary } from "@/lib/workspace";

const GROUP_ICONS: Record<CommandGroup, LucideIcon> = {
  "Next step": ArrowRight,
  "This project": FolderOpen,
  "Go to": Compass,
  Projects: Folder,
  "Ask PeakSift": Sparkles,
};

/**
 * The command menu: type to jump to a page or project, or to ask PeakSift. A combobox — the
 * cursor stays in the field, arrow keys move the highlighted command, Enter runs it, Escape
 * closes and focus returns to where it was.
 */
export function CommandMenu({
  open,
  onClose,
  projects,
  returnTo,
}: {
  open: boolean;
  onClose: () => void;
  projects: Project[] | null;
  /** What had focus before the menu opened (Ask PeakSift returns focus there when it closes). */
  returnTo: HTMLElement | null;
}) {
  // The body mounts each time the menu opens, so it always starts empty.
  return (
    <Dialog open={open} onClose={onClose} title="Search or ask" placement="palette" width="38rem" hideTitle>
      <MenuBody onClose={onClose} projects={projects} returnTo={returnTo} />
    </Dialog>
  );
}

function MenuBody({
  onClose,
  projects,
  returnTo,
}: {
  onClose: () => void;
  projects: Project[] | null;
  returnTo: HTMLElement | null;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { openCopilot } = useCopilot();
  const listId = useId();
  const list = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [server, setServer] = useState<Pick<CommandSource, "next" | "hasSource">>({ next: null, hasSource: null });

  const scope = copilotScope(pathname);
  const project = scope.projectId ? (projects ?? []).find((p) => p.id === scope.projectId) : undefined;

  // The server's next step for where the creator is (the same one Home and the Overview show),
  // and whether the project has a video yet (for the suggested questions).
  useEffect(() => {
    let cancelled = false;
    const request: Promise<Pick<CommandSource, "next" | "hasSource">> = scope.projectId
      ? getProjectSummary(scope.projectId).then((summary) => ({ next: summary.next_action, hasSource: summary.source !== null }))
      : getHome().then((home) => {
          const first = home.continue_items[0];
          return { next: first ? { ...first, projectName: first.project_name } : null, hasSource: null };
        });
    request.then((value) => !cancelled && setServer(value)).catch(() => undefined); // the menu works without it
    return () => {
      cancelled = true;
    };
  }, [scope.projectId]);

  const commands = useMemo(
    () =>
      buildCommands({
        page: scope.page,
        project: project ? { id: project.id, name: project.name } : null,
        projects: projects ?? [],
        ...server,
      }),
    [scope.page, project, projects, server],
  );
  const shown = useMemo(() => filterCommands(commands, query), [commands, query]);
  const groups = useMemo(() => groupCommands(shown), [shown]);
  const positions = useMemo(() => new Map(shown.map((command, position) => [command.id, position])), [shown]);
  const optionId = (index: number) => `${listId}-option-${index}`;
  const current = Math.min(active, shown.length - 1);

  useEffect(() => {
    list.current?.querySelector(`[id="${CSS.escape(optionId(current))}"]`)?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- optionId only depends on listId
  }, [current]);

  function run(command: Command) {
    onClose();
    if (command.run.kind === "ask") openCopilot(command.run.question, returnTo);
    else router.push(command.run.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current + step + shown.length) % shown.length);
    } else if (event.key === "Enter" && shown[current]) {
      event.preventDefault();
      run(shown[current]);
    }
  }

  return (
    <div className="-mt-3 flex flex-col gap-3">
        <div className="relative">
          <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-subtle" />
          <input
            data-autofocus
            type="text"
            role="combobox"
            aria-label="Search pages and projects, or ask PeakSift"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={shown.length ? optionId(current) : undefined}
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="go"
            placeholder="Go to a page or project, or ask PeakSift…"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            className={`${inputClasses} pl-10`}
          />
        </div>
        <div ref={list} id={listId} role="listbox" aria-label="Commands" className="-mx-2 flex flex-col gap-3">
          {groups.map(({ group, commands: items }) => {
            const Icon = GROUP_ICONS[group];
            const headingId = `${listId}-${group.replace(/\s+/g, "-")}`;
            return (
              <div key={group} role="group" aria-labelledby={headingId} className="flex flex-col">
                <p id={headingId} className="px-2 pb-1 text-xs font-medium tracking-wide text-subtle uppercase">
                  {group}
                </p>
                {items.map((command) => {
                  const position = positions.get(command.id) ?? 0;
                  const selected = position === current;
                  return (
                    <div
                      key={command.id}
                      id={optionId(position)}
                      role="option"
                      aria-selected={selected}
                      onMouseMove={() => position !== current && setActive(position)}
                      onClick={() => run(command)}
                      className={`flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 text-sm pointer-coarse:min-h-11 ${
                        selected ? "bg-white/[0.08] text-foreground" : "text-muted"
                      }`}
                    >
                      <Icon aria-hidden="true" className={`size-4 shrink-0 ${group === "Ask PeakSift" ? "text-accent-soft" : ""}`} />
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-foreground">
                          {command.id === "ask:typed" ? <>Ask PeakSift: “{command.label}”</> : command.label}
                        </span>
                        {command.hint ? <span className="truncate text-small text-subtle">{command.hint}</span> : null}
                      </span>
                      {selected ? (
                        <kbd aria-hidden="true" className="hidden shrink-0 font-sans text-xs text-subtle sm:inline">
                          Enter
                        </kbd>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
        <p className="border-t border-border pt-3 text-xs text-subtle">
          <span className="hidden sm:inline">↑ ↓ to move · Enter to open · Esc to close · </span>
          Questions go to Ask PeakSift, which answers from your own projects.
        </p>
    </div>
  );
}
