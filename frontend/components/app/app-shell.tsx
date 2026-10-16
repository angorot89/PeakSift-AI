"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FolderOpen, LayoutGrid, LogOut, Settings } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { LogoMark } from "@/components/logo";
import { Button } from "@/components/ui/button";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/projects", label: "Projects", icon: FolderOpen },
  { href: "/settings", label: "Settings", icon: Settings },
];

/** Chrome for the signed-in area: brand, section nav, user, logout. */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    await logout();
    // RequireAuth also sends signed-out users here; doing it explicitly keeps it deterministic.
    router.replace("/login");
  }

  return (
    <>
      <header className="sticky top-0 z-50 border-b border-border bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3 sm:gap-6">
            <Link
              href="/dashboard"
              className="flex shrink-0 items-center gap-2.5 rounded-md font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            >
              <LogoMark />
              <span className="hidden sm:inline">
                PeakSift <span className="text-muted">AI</span>
              </span>
            </Link>
            <nav aria-label="App" className="flex items-center gap-1">
              {navItems.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`inline-flex h-8 items-center gap-2 rounded-lg px-2.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      active
                        ? "bg-white/[0.08] text-foreground"
                        : "text-muted hover:bg-white/[0.04] hover:text-foreground"
                    }`}
                  >
                    <item.icon aria-hidden="true" className="size-4" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {user ? (
              <span className="hidden items-center gap-2 md:flex" title={user.email}>
                <span
                  aria-hidden="true"
                  className="flex size-7 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-foreground uppercase ring-1 ring-white/10"
                >
                  {user.email.charAt(0)}
                </span>
                <span className="max-w-[22ch] truncate text-sm text-muted">{user.email}</span>
              </span>
            ) : null}
            <Button variant="ghost" size="sm" onClick={handleLogout} disabled={loggingOut} aria-label="Log out">
              <LogOut aria-hidden="true" />
              <span className="hidden sm:inline">{loggingOut ? "Logging out…" : "Log out"}</span>
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">{children}</main>
    </>
  );
}
