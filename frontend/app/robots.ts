import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/** Search engines may read the website; the signed-in app is private. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/home", "/projects", "/shorts", "/schedule", "/analytics", "/brand", "/settings", "/morocco", "/dashboard"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
