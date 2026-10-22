import type { MetadataRoute } from "next";
import { helpTopics } from "@/features/help/content";
export default function sitemap(): MetadataRoute.Sitemap {
  const base = (process.env.SITE_URL ?? "https://xuansi.kukude.top").replace(
    /\/$/,
    "",
  );
  return [
    "",
    "/features",
    "/download",
    "/resources",
    "/docs",
    "/faq",
    "/privacy",
    "/terms",
    "/licenses",
    "/changelog",
    ...helpTopics.map((topic) => `/docs/${topic.slug}`),
  ].map((path) => ({
    url: base + path,
    changeFrequency: "weekly",
    priority: path === "" ? 1 : 0.7,
  }));
}
