// Pure navigation rules (no React): the global destinations, the sections inside a project,
// and which one a path belongs to. Unit-tested with node --test.

export type GlobalKey = "home" | "projects" | "analytics" | "brand" | "settings";

export const GLOBAL_NAV: { key: GlobalKey; href: string; label: string }[] = [
  { key: "home", href: "/home", label: "Home" },
  { key: "projects", href: "/projects", label: "Projects" },
  { key: "analytics", href: "/analytics", label: "Analytics" },
  { key: "brand", href: "/brand", label: "Brand Studio" },
];
export const SETTINGS_NAV = { key: "settings" as const, href: "/settings", label: "Settings" };

export type ProjectSection = "overview" | "source" | "clips" | "assets" | "analytics";

export const PROJECT_SECTIONS: { key: ProjectSection; label: string; path: string }[] = [
  { key: "overview", label: "Overview", path: "" },
  { key: "source", label: "Source", path: "/source" },
  { key: "clips", label: "Clips", path: "/clips" },
  { key: "assets", label: "Assets", path: "/assets" },
  { key: "analytics", label: "Analytics", path: "/analytics" },
];

export const projectHref = (projectId: string, section: ProjectSection = "overview") =>
  `/projects/${projectId}${PROJECT_SECTIONS.find((s) => s.key === section)!.path}`;

export const clipHref = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}`;

/** The global destination a path belongs to (a project is part of Projects). */
export function activeGlobal(pathname: string): GlobalKey | null {
  if (pathname === "/home" || pathname.startsWith("/home/")) return "home";
  if (pathname === "/projects" || pathname.startsWith("/projects/")) return "projects";
  if (pathname === "/analytics" || pathname.startsWith("/analytics/")) return "analytics";
  if (pathname === "/brand" || pathname.startsWith("/brand/")) return "brand";
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return "settings";
  return null;
}

export type ProjectLocation = {
  projectId: string;
  section: ProjectSection;
  /** Inside one clip (the editor, Auto Edit or the create flow), not a section page. */
  clipId: string | null;
};

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const PROJECT_PATH = new RegExp(`^/projects/(${UUID})(?:/([a-z-]+))?(?:/(${UUID}))?`, "i");

/** Where inside a project a path is, or null outside projects (and for /projects/new). */
export function projectLocation(pathname: string): ProjectLocation | null {
  const match = PROJECT_PATH.exec(pathname);
  if (!match) return null;
  const [, projectId, segment, clipId] = match;
  if (!segment) return { projectId, section: "overview", clipId: null };
  const section = PROJECT_SECTIONS.find((s) => s.path === `/${segment}`)?.key;
  if (!section) return { projectId, section: "overview", clipId: null };
  return { projectId, section, clipId: section === "clips" ? (clipId ?? null) : null };
}
