"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { AFTER_AUTH_PATH } from "@/lib/auth";

/** Sends signed-in users away from the login/register pages. */
export function useRedirectWhenAuthenticated() {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace(AFTER_AUTH_PATH);
  }, [status, router]);
}
