"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";

/** Right-hand side of the site header: sign-in links or the signed-in user. */
export function HeaderAuth() {
  const { user, status, logout } = useAuth();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  if (status === "loading") {
    // Same footprint as the buttons so the header does not jump once we know.
    return <div aria-hidden="true" className="h-10 w-32 rounded-control bg-surface-2" />;
  }

  if (user) {
    async function handleLogout() {
      setLoggingOut(true);
      await logout();
      router.push("/");
      setLoggingOut(false);
    }

    return (
      <div className="flex items-center gap-2 sm:gap-3">
        <span className="hidden sm:block">
          <Button variant="ghost" onClick={handleLogout} disabled={loggingOut}>
            {loggingOut ? "Logging out…" : "Log out"}
          </Button>
        </span>
        <ButtonLink href="/home">Open PeakSift</ButtonLink>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4">
      <Link
        href="/login"
        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-sm text-sm font-medium text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
      >
        Log in
      </Link>
      <ButtonLink href="/register">Sign up</ButtonLink>
    </div>
  );
}
