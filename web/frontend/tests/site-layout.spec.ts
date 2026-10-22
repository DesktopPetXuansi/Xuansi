import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { publicVisitor } from "./public-fixtures";

const routes = [
  "/",
  "/download",
  "/resources",
  "/changelog",
  "/docs/chat",
  "/privacy",
  "/terms",
];
const screenshotDirectory = resolve(
  "../.runtime/screenshots/site-audit-2026-10-22/final",
);

test.beforeAll(async () => {
  await mkdir(screenshotDirectory, { recursive: true });
});

// 宽度覆盖手机、平板和桌面；校验布局结果，不依赖具体 CSS 类或像素快照。
for (const width of [320, 390, 768, 1440]) {
  test(`${width}px 公开页面无溢出、元数据正确且没有脚本异常`, async ({
    page,
    baseURL,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await publicVisitor(page);
    await page.setViewportSize({ width, height: 900 });
    for (const route of routes) {
      const response = await page.goto(route, { waitUntil: "networkidle" });
      expect(response?.status(), route).toBe(200);
      await expect(
        page.getByRole("main").getByRole("heading", { level: 1 }),
      ).toHaveCount(1);
      await expect(page).toHaveTitle(/玄司 Xuansi/);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth,
      );
      expect(overflow, `${width}px ${route}`).toBe(false);
      await expect(page.locator('link[rel="canonical"]')).toHaveJSProperty(
        "href",
        new URL(route, process.env.SITE_URL ?? baseURL).href,
      );
      await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
        "content",
        /\/brand\/share\.png$/,
      );
      if (route === "/" || route === "/download") {
        await page.screenshot({
          path: resolve(
            screenshotDirectory,
            `${route === "/" ? "home" : "download"}-${width}.png`,
          ),
          fullPage: true,
        });
      }
    }
    expect(errors).toEqual([]);
  });
}
