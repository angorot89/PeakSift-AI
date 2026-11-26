"use client";

import {
  BarChart3,
  CalendarClock,
  ChevronsUpDown,
  FolderOpen,
  Home,
  LogOut,
  Menu as MenuIcon,
  Palette,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  Smartphone,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { CommandMenu } from "@/components/app/command-menu";
import { ShellSearchContext, useIsMac } from "@/components/app/shell-search";
import { CopilotPanel } from "@/components/app/copilot/copilot-panel";
import { CopilotProvider, useCopilot } from "@/components/app/copilot/copilot-provider";
import { useAuth } from "@/components/auth/auth-provider";
import { LogoMark } from "@/components/logo";
import { Dialog } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { Menu } from "@/components/ui/menu";
import { isCommandShortcut } from "@/lib/command-menu";
import { activeGlobal, GLOBAL_NAV, projectLocation, SETTINGS_NAV, type GlobalKey } from "@/lib/navigation";
import { listProjects, type Project } from "@/lib/projects";
import { useStoredFlag } from "@/lib/use-stored-flag";

const ICONS: Record<GlobalKey, LucideIcon> = {
  home: Home,
  projects: FolderOpen,
  shorts: Smartphone,
  schedule: CalendarClock,
  analytics: BarChart3,
  brand: Palette,
  settings: Settings,
};
const RECENT_PROJECTS = 3;
const COLLAPSE_KEY = "peaksift.sidebar.collapsed";

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  collapsed,
  onNavigate,
  nested = false,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
  nested?: boolean;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
      className={`group flex items-center gap-3 rounded-control transition-[color,background-color,box-shadow] duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:min-h-11 ${
        collapsed ? "justify-center" : ""
      } ${nested ? "min-h-9 pl-11 pr-2.5 text-small" : "min-h-11 px-3 text-[0.9375rem]"} ${
        active
          ? nested
            ? "bg-surface-2 font-medium text-foreground"
            : "nav-active font-medium text-foreground"
          : "text-muted hover:bg-surface hover:text-foreground"
      }`}
    >
      {nested ? null : (
        <Icon aria-hidden="true" className={`size-5 shrink-0 ${active ? "text-foreground" : "text-subtle group-hover:text-muted"}`} />
      )}
      <span className={collapsed ? "sr-only" : "min-w-0 truncate"}>{label}</span>
    </Link>
  );
}

/** Ask PeakSift: opens the assistant for the page the creator is on. */
function AskButton({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { open, openCopilot } = useCopilot();
  return (
    <button
      type="button"
      onClick={() => {
        onNavigate?.(); // on phones the navigation sheet closes first
        openCopilot();
      }}
      aria-expanded={open}
      title={collapsed ? "Ask PeakSift" : undefined}
      className={`group flex min-h-11 items-center gap-3 rounded-control border px-3 text-[0.9375rem] font-medium text-foreground transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
        collapsed ? "justify-center px-0" : ""
      } ${open ? "border-accent/60 bg-surface-2" : "border-border-strong bg-surface hover:bg-surface-2"}`}
    >
      <Sparkles aria-hidden="true" className="size-5 shrink-0 text-accent-soft" />
      <span className={collapsed ? "sr-only" : "min-w-0 truncate"}>Ask PeakSift</span>
    </button>
  );
}

/** Everything in the sidebar: brand, the quick action, destinations, recent projects, account. */
function SidebarContent({
  collapsed,
  onToggle,
  onNavigate,
  onSearch,
  projects,
}: {
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
  onSearch: () => void;
  projects: Project[] | null;
}) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const active = activeGlobal(pathname);
  const current = projectLocation(pathname)?.projectId ?? null;
  const [loggingOut, setLoggingOut] = useState(false);
  // The project being worked on stays listed even when it is not among the most recent.
  const recent = (projects ?? []).slice(0, RECENT_PROJECTS);
  const open = current ? (projects ?? []).find((p) => p.id === current) : undefined;
  const listed = open && !recent.some((p) => p.id === open.id) ? [open, ...recent.slice(0, RECENT_PROJECTS - 1)] : recent;

  async function handleLogout() {
    setLoggingOut(true);
    await logout();
    router.replace("/login"); // RequireAuth also redirects; this keeps it deterministic
  }

  const name = user ? user.email.split("@")[0] : "";

  return (
    <div className="flex h-full flex-col gap-6">
      <div className={`flex items-center gap-2 ${collapsed ? "flex-col" : "justify-between"}`}>
        <Link
          href="/home"
          onClick={onNavigate}
          className="flex min-h-11 items-center gap-2.5 rounded-control px-1 text-lg font-bold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <LogoMark className="size-8" />
          <span className={collapsed ? "sr-only" : ""}>
            PeakSift <span className="font-normal text-subtle">AI</span>
          </span>
        </Link>
        {onToggle ? (
          <IconButton aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={onToggle} size="sm">
            {collapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}
          </IconButton>
        ) : null}
      </div>

      <nav aria-label="Main" className="flex flex-col gap-1">
        {[...GLOBAL_NAV, SETTINGS_NAV].map((item) => (
          <div key={item.key} className="flex flex-col gap-0.5">
            <NavLink
              href={item.href}
              label={item.label}
              icon={ICONS[item.key]}
              active={active === item.key && !(item.key === "projects" && current)}
              collapsed={collapsed}
              onNavigate={onNavigate}
            />
            {item.key === "projects" && !collapsed && listed.length > 0 ? (
              <ul aria-label="Recent projects" className="flex flex-col gap-0.5">
                {listed.map((project) => (
                  <li key={project.id}>
                    <NavLink
                      href={`/projects/${project.id}`}
                      label={project.name}
                      icon={FolderOpen}
                      active={project.id === current}
                      collapsed={false}
                      onNavigate={onNavigate}
                      nested
                    />
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        {onSearch ? (
          // Phones: the navigation sheet keeps a way into search (the top bar has one too).
          <button
            type="button"
            onClick={onSearch}
            aria-haspopup="dialog"
            className="flex min-h-11 items-center gap-3 rounded-control px-3 text-[0.9375rem] text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent lg:hidden"
          >
            <Search aria-hidden="true" className="size-5 shrink-0 text-subtle" />
            Search
          </button>
        ) : null}
        <AskButton collapsed={collapsed} onNavigate={onNavigate} />
        {user ? (
          <Menu
            label={`Account: ${user.email}`}
            side="above"
            align="start"
            className="w-full"
            triggerClassName={`flex min-h-14 w-full items-center gap-3 rounded-control border border-border bg-surface text-left transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              collapsed ? "justify-center px-0" : "px-2.5"
            }`}
            trigger={
              <>
                <span
                  aria-hidden="true"
                  className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-3 text-sm font-semibold text-foreground uppercase"
                >
                  {user.email.charAt(0)}
                </span>
                {collapsed ? null : (
                  <>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-foreground">{name}</span>
                      <span className="block truncate text-caption text-subtle">{user.email}</span>
                    </span>
                    <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 text-subtle" />
                  </>
                )}
              </>
            }
            items={[
              { label: "Settings", icon: Settings, onSelect: () => { onNavigate?.(); router.push(SETTINGS_NAV.href); } },
              { label: loggingOut ? "Logging out…" : "Log out", icon: LogOut, onSelect: handleLogout, disabled: loggingOut },
            ]}
          />
        ) : null}
      </div>
    </div>
  );
}

/** The signed-in area: a sidebar on large screens, a top bar and a navigation sheet on phones,
 * and Ask PeakSift (a side panel, or a full-height sheet on phones). */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <CopilotProvider>
      <Shell>{children}</Shell>
      <CopilotPanel />
    </CopilotProvider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const copilot = useCopilot();
  // A preference of this browser only; everything works without it.
  const [collapsed, setCollapsed] = useStoredFlag(COLLAPSE_KEY);
  const [drawer, setDrawer] = useState(false);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [menu, setMenu] = useState(false);
  const [menuReturn, setMenuReturn] = useState<HTMLElement | null>(null);
  const mac = useIsMac();
  const toggle = () => setCollapsed(!collapsed);

  function openMenu() {
    setMenuReturn(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setDrawer(false); // on phones the navigation sheet makes way
    setMenu(true);
  }

  // Cmd/Ctrl+K opens (or closes) the command menu — not over another dialog, and the editor has
  // no shortcut of its own on K.
  useEffect(() => {
    if (mac === null) return;
    function onKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing || event.repeat || !isCommandShortcut(event, mac === true)) return;
      if (menu) {
        event.preventDefault();
        setMenu(false);
      } else if (!document.querySelector("dialog[open]")) {
        event.preventDefault();
        setMenuReturn(document.activeElement instanceof HTMLElement ? document.activeElement : null);
        setMenu(true);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mac, menu]);

  // Recent projects: refreshed on navigation, so a new or renamed project shows up.
  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((list) => !cancelled && setProjects(list))
      .catch(() => !cancelled && setProjects([]));
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  return (
    <ShellSearchContext.Provider value={openMenu}>
    <div className="flex min-h-dvh bg-background">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-control focus:bg-foreground focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-background"
      >
        Skip to content
      </a>
      <aside
        aria-label="Sidebar"
        className={`sticky top-0 hidden h-dvh bg-chrome shrink-0 border-r border-border px-3 py-5 transition-[width] duration-200 lg:block ${
          collapsed ? "w-[4.75rem]" : "w-64"
        }`}
      >
        <SidebarContent collapsed={collapsed} onToggle={toggle} onSearch={openMenu} projects={projects} />
      </aside>

      {/* On very wide screens an open Ask PeakSift panel sits beside the page instead of over it. */}
      <div className={`flex min-w-0 flex-1 flex-col transition-[padding] duration-200 ${copilot.open ? "2xl:pr-[28rem]" : ""}`}>
        <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b border-border bg-chrome px-3 lg:hidden">
          <IconButton aria-label="Open navigation" aria-haspopup="dialog" aria-expanded={drawer} onClick={() => setDrawer(true)}>
            <MenuIcon aria-hidden="true" />
          </IconButton>
          <Link href="/home" className="flex min-h-11 items-center gap-2 rounded-md px-1 font-bold tracking-tight">
            <LogoMark className="size-7" />
            PeakSift <span className="font-normal text-subtle">AI</span>
          </Link>
          <IconButton aria-label="Search" aria-haspopup="dialog" onClick={openMenu} className="ml-auto">
            <Search aria-hidden="true" />
          </IconButton>
          <IconButton
            aria-label="Ask PeakSift"
            aria-expanded={copilot.open}
            onClick={() => copilot.openCopilot()}
            className="text-accent-soft"
          >
            <Sparkles aria-hidden="true" />
          </IconButton>
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[80rem] flex-1 px-4 py-6 outline-none sm:px-6 lg:px-10 lg:py-9">
          {children}
        </main>
      </div>

      <Dialog open={drawer} onClose={() => setDrawer(false)} title="Navigation" placement="left" hideTitle>
        <SidebarContent collapsed={false} onNavigate={() => setDrawer(false)} onSearch={openMenu} projects={projects} />
      </Dialog>
      <CommandMenu open={menu} onClose={() => setMenu(false)} projects={projects} returnTo={menuReturn} />
    </div>
    </ShellSearchContext.Provider>
  );
}
