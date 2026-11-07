import { expect, test } from "@playwright/test";
import { publicVisitor } from "./public-fixtures";

// 首页截图模块已移除：桌面和手机都不应继续请求旧截图。
for (const [width, dpr] of [
  [1440, 2],
  [390, 3],
]) {
  test(`${width}px / ${dpr}x 首页不加载已移除的客户端截图`, async ({
    browser,
    baseURL,
  }) => {
    const context = await browser.newContext({
      baseURL,
      viewport: { width, height: 1000 },
      deviceScaleFactor: dpr,
      reducedMotion: "reduce",
    });
    try {
      const page = await context.newPage();
      const screenshots: string[] = [];
      page.on("request", (request) => {
        if (new URL(request.url()).pathname.startsWith("/product/client-")) {
          screenshots.push(request.url());
        }
      });
      await publicVisitor(page);
      await page.goto("/", { waitUntil: "networkidle" });
      await expect(page.locator("#product-preview")).toHaveCount(0);
      await expect(
        page.getByAltText("玄司角色：黑金服饰与长发的桌面伙伴"),
      ).toBeVisible();
      expect(screenshots).toEqual([]);
    } finally {
      await context.close();
    }
  });
}
