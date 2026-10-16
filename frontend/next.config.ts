import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The production container runs Next's self-contained server (deploy/frontend.Dockerfile
  // sets NEXT_OUTPUT=standalone); local `next start` keeps the default output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
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
