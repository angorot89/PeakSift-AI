// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { apiOrigin, contentSecurityPolicy, securityHeaders } from "./security-headers.ts";

const directive = (policy: string, name: string) =>
  policy.split("; ").find((d) => d.startsWith(`${name} `)) ?? "";

describe("content security policy", () => {
  it("allows only the API origin besides itself, for data and media", () => {
    const policy = contentSecurityPolicy("https://api.peaksift.example");
    assert.equal(directive(policy, "connect-src"), "connect-src 'self' https://api.peaksift.example");
    assert.equal(directive(policy, "media-src"), "media-src 'self' https://api.peaksift.example");
    assert.equal(directive(policy, "default-src"), "default-src 'self'");
  });

  it("needs nothing extra when the API shares the origin", () => {
    assert.equal(apiOrigin("/api"), "");
    assert.equal(directive(contentSecurityPolicy("/api"), "media-src"), "media-src 'self'");
  });

  it("never allows eval, plugins, framing or foreign forms in production", () => {
    const policy = contentSecurityPolicy("/api");
    assert.doesNotMatch(policy, /unsafe-eval/);
    for (const rule of ["object-src 'none'", "frame-ancestors 'none'", "form-action 'self'", "base-uri 'self'"]) {
      assert.ok(policy.includes(rule), rule);
    }
    assert.ok(policy.endsWith("upgrade-insecure-requests"));
    assert.ok(contentSecurityPolicy("https://api.example.com").endsWith("upgrade-insecure-requests"));
    assert.doesNotMatch(contentSecurityPolicy("http://localhost:8000"), /upgrade-insecure-requests/);
  });

  it("embeds only YouTube's privacy-enhanced player and its thumbnails", () => {
    const policy = contentSecurityPolicy("/api");
    assert.equal(directive(policy, "frame-src"), "frame-src https://www.youtube-nocookie.com");
    assert.equal(directive(policy, "img-src"), "img-src 'self' data: https://i.ytimg.com");
  });

  it("allows what the development server needs only in development", () => {
    const policy = contentSecurityPolicy("http://localhost:8000", { development: true });
    assert.match(directive(policy, "script-src"), /'unsafe-eval'/);
    assert.match(directive(policy, "connect-src"), /ws:/);
    assert.doesNotMatch(policy, /upgrade-insecure-requests/);
  });

  it("ignores API values that are not http(s) origins", () => {
    assert.equal(apiOrigin("javascript:alert(1)"), "");
    assert.equal(apiOrigin("not a url"), "");
  });
});

describe("headers", () => {
  it("sends the standard protections with every page", () => {
    const keys = securityHeaders("/api").map((h) => h.key);
    assert.deepEqual(keys, [
      "Content-Security-Policy",
      "X-Content-Type-Options",
      "X-Frame-Options",
      "Referrer-Policy",
      "Permissions-Policy",
      "Cross-Origin-Opener-Policy",
    ]);
  });
});
