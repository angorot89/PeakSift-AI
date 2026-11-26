// The public website's address, for absolute links (sitemap, share images, canonical URLs).
// Set NEXT_PUBLIC_SITE_URL in production; locally it is the dev server.
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");
