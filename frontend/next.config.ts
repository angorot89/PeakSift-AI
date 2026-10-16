import type { NextConfig } from "next";
import { securityHeaders } from "./lib/security-headers";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // The production container runs Next's self-contained server (deploy/frontend.Dockerfile
  // sets NEXT_OUTPUT=standalone); local `next start` keeps the default output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Security headers (CSP, framing, sniffing, referrer, permissions) on every page.
  async headers() {
    const development = process.env.NODE_ENV !== "production";
    return [{ source: "/:path*", headers: securityHeaders(API_URL, { development }) }];
  },
  poweredByHeader: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
