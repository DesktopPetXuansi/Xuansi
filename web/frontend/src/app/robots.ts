import type { MetadataRoute } from "next";
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/dashboard", "/admin", "/authorize", "/api", "/oauth"],
    },
    sitemap: `${(process.env.SITE_URL ?? "https://xuansi.kukude.top").replace(/\/$/, "")}/sitemap.xml`,
  };
}
