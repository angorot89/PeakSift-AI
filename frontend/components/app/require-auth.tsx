"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { LoadingState } from "@/components/app/states";

/**
 * Client-side gate for the authenticated area. This only improves the experience;
 * the API enforces authorization on every request.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <main className="flex flex-1 items-center justify-center px-6 py-24">
        <LoadingState label="Checking your session…" />
      </main>
    );
  }

  return <>{children}</>;
}
