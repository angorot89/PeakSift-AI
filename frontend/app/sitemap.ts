import type { MetadataRoute } from "next";
import { AUDIENCES, GUIDES, TOOLS } from "@/components/landing/content";
import { SITE_URL } from "@/lib/site";

/** Every public page of the website (the signed-in app is not listed). */
export default function sitemap(): MetadataRoute.Sitemap {
  const pages = [
    "",
    "/features",
    "/pricing",
    "/about",
    "/guides",
    "/privacy",
    "/terms",
    "/privacy-policy",
    "/login",
    "/register",
    ...TOOLS.map((tool) => `/features/${tool.slug}`),
    ...AUDIENCES.map((audience) => `/made-for/${audience.slug}`),
    ...GUIDES.map((guide) => `/guides/${guide.slug}`),
  ];
  return pages.map((path) => ({ url: `${SITE_URL}${path}`, changeFrequency: "weekly", priority: path === "" ? 1 : 0.7 }));
}
