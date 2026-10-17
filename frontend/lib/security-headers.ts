/**
 * Security headers for every page the frontend serves (pure: used by next.config.ts and
 * unit-tested with node --test, so no imports).
 *
 * The Content-Security-Policy allows only what PeakSift loads: its own scripts, styles and
 * self-hosted fonts, and the API origin for data and media (`<video>`/`<audio>` sources).
 * Next.js renders inline hydration scripts and React inline styles, so `'unsafe-inline'` is
 * needed for those two directives; no `eval` is ever allowed in production, no other
 * origin can run code, and the app cannot be framed. Leaving for Google's consent page is a
 * top-level navigation, which CSP does not restrict.
 */

export type Header = { key: string; value: string };

/** The API's origin, or "" when it is served from the same origin (a path like "/api"). */
export function apiOrigin(apiUrl: string): string {
  try {
    const url = new URL(apiUrl);
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : "";
  } catch {
    return ""; // relative: same origin
  }
}

export function contentSecurityPolicy(apiUrl: string, { development = false } = {}): string {
  const api = apiOrigin(apiUrl);
  const withApi = (...sources: string[]) => [...sources, ...(api ? [api] : [])].join(" ");
  const directives: Record<string, string> = {
    "default-src": "'self'",
    // Development only: React Refresh evaluates code and the dev server opens a websocket.
    "script-src": development ? "'self' 'unsafe-inline' 'unsafe-eval'" : "'self' 'unsafe-inline'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": withApi("'self'", "data:"),
    "font-src": "'self' data:",
    "media-src": withApi("'self'"),
    "connect-src": development ? withApi("'self'", "ws:") : withApi("'self'"),
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "frame-ancestors": "'none'",
    "frame-src": "'none'",
    "worker-src": "'self'",
    "manifest-src": "'self'",
  };
  const policy = Object.entries(directives).map(([name, value]) => `${name} ${value}`);
  // Only where everything is HTTPS (same-origin or an https API): a local production build
  // talking to an http:// API must keep working.
  if (!development && (api === "" || api.startsWith("https:"))) policy.push("upgrade-insecure-requests");
  return policy.join("; ");
}

export function securityHeaders(apiUrl: string, { development = false } = {}): Header[] {
  return [
    { key: "Content-Security-Policy", value: contentSecurityPolicy(apiUrl, { development }) },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ];
}
