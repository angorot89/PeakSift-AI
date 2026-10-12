"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { LogoMark } from "@/components/logo";
import { Button } from "@/components/ui/button";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
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
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-6">
          <div className="flex min-w-0 items-center gap-6">
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
                    className={`rounded-full px-3 py-1.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      active
                        ? "bg-white/[0.08] text-foreground"
                        : "text-muted hover:bg-white/[0.04] hover:text-foreground"
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {user ? (
              <span className="hidden max-w-[20ch] truncate text-sm text-muted md:inline" title={user.email}>
                {user.email}
              </span>
            ) : null}
            <Button variant="secondary" onClick={handleLogout} disabled={loggingOut}>
              {loggingOut ? "Logging out…" : "Log out"}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">{children}</main>
    </>
  );
}
