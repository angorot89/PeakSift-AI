"use client";

import {
  BarChart3,
  Folder,
  FolderOpen,
  Home,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { LogoMark } from "@/components/logo";
import { Dialog } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { activeGlobal, GLOBAL_NAV, projectLocation, SETTINGS_NAV, type GlobalKey } from "@/lib/navigation";
import { listProjects, type Project } from "@/lib/projects";

const ICONS: Record<GlobalKey, LucideIcon> = {
  home: Home,
  projects: FolderOpen,
  analytics: BarChart3,
  settings: Settings,
};
const RECENT_PROJECTS = 3;
const COLLAPSE_KEY = "peaksift.sidebar.collapsed";

// The sidebar preference lives in this browser only (a convenience; everything works without it).
const listeners = new Set<() => void>();
function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}
function writeCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0");
  } catch {
    // storage unavailable (private mode): the choice lasts until reload
  }
  listeners.forEach((listener) => listener());
}
function subscribeCollapsed(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

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
      className={`group flex min-h-10 items-center gap-3 rounded-lg px-2.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
        collapsed ? "justify-center" : ""
      } ${nested ? "min-h-9 pl-9 text-small" : ""} ${
        active ? "bg-white/[0.08] font-medium text-foreground" : "text-muted hover:bg-white/[0.04] hover:text-foreground"
      }`}
    >
      {nested ? null : <Icon aria-hidden="true" className={`size-[18px] shrink-0 ${active ? "text-accent-soft" : ""}`} />}
      <span className={collapsed ? "sr-only" : "min-w-0 truncate"}>{label}</span>
    </Link>
  );
}

/** Everything in the sidebar: brand, the quick action, destinations, recent projects, account. */
function SidebarContent({
  collapsed,
  onToggle,
  onNavigate,
  projects,
}: {
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
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

  return (
    <div className="flex h-full flex-col gap-4">
      <div className={`flex items-center gap-2 ${collapsed ? "flex-col" : "justify-between"}`}>
        <Link
          href="/home"
          onClick={onNavigate}
          className="flex min-h-10 items-center gap-2.5 rounded-md px-1 font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <LogoMark />
          <span className={collapsed ? "sr-only" : ""}>
            PeakSift <span className="text-muted">AI</span>
          </span>
        </Link>
        {onToggle ? (
          <IconButton aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={onToggle} size="sm">
            {collapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}
          </IconButton>
        ) : null}
      </div>

      <Link
        href="/projects/new"
        onClick={onNavigate}
        title={collapsed ? "New project" : undefined}
        className={`flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border-strong bg-surface-2 text-sm font-medium text-foreground transition-colors hover:border-white/25 hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          collapsed ? "size-10 self-center" : "px-3"
        }`}
      >
        <Plus aria-hidden="true" className="size-4" />
        <span className={collapsed ? "sr-only" : ""}>New project</span>
      </Link>

      <nav aria-label="Main" className="flex flex-col gap-0.5">
        {GLOBAL_NAV.map((item) => (
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
                      icon={Folder}
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

      <div className="mt-auto flex flex-col gap-1 border-t border-border pt-3">
        <NavLink
          href={SETTINGS_NAV.href}
          label={SETTINGS_NAV.label}
          icon={Settings}
          active={active === "settings"}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        <div className={`flex items-center gap-2 rounded-lg px-1.5 py-1 ${collapsed ? "flex-col" : ""}`}>
          {user ? (
            <span
              aria-hidden="true"
              className="flex size-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-foreground uppercase ring-1 ring-white/10"
            >
              {user.email.charAt(0)}
            </span>
          ) : null}
          {user && !collapsed ? (
            <span className="min-w-0 flex-1 truncate text-small text-muted" title={user.email}>
              {user.email}
            </span>
          ) : null}
          <IconButton aria-label={loggingOut ? "Logging out" : "Log out"} onClick={handleLogout} disabled={loggingOut} size="sm">
            <LogOut aria-hidden="true" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}

/** The signed-in area: a sidebar on large screens, a top bar and a navigation sheet on phones. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const collapsed = useSyncExternalStore(subscribeCollapsed, readCollapsed, () => false);
  const [drawer, setDrawer] = useState(false);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const toggle = () => writeCollapsed(!collapsed);

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
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-lg focus:bg-foreground focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-background"
      >
        Skip to content
      </a>
      <aside
        aria-label="Sidebar"
        className={`sticky top-0 hidden h-dvh shrink-0 border-r border-border bg-surface/60 px-3 py-4 transition-[width] duration-200 lg:block ${
          collapsed ? "w-[4.5rem]" : "w-60"
        }`}
      >
        <SidebarContent collapsed={collapsed} onToggle={toggle} projects={projects} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur-xl lg:hidden">
          <IconButton aria-label="Open navigation" aria-haspopup="dialog" aria-expanded={drawer} onClick={() => setDrawer(true)}>
            <Menu aria-hidden="true" />
          </IconButton>
          <Link href="/home" className="flex min-h-10 items-center gap-2 rounded-md px-1 font-semibold tracking-tight">
            <LogoMark className="size-6" />
            PeakSift <span className="text-muted">AI</span>
          </Link>
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[76rem] flex-1 px-4 py-6 outline-none sm:px-6 lg:px-10 lg:py-8">
          {children}
        </main>
      </div>

      <Dialog open={drawer} onClose={() => setDrawer(false)} title="Navigation" placement="left" hideTitle>
        <SidebarContent collapsed={false} onNavigate={() => setDrawer(false)} projects={projects} />
      </Dialog>
    </div>
  );
}
