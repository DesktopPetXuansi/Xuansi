import { expect, test } from "@playwright/test";
import { publicVisitor } from "./public-fixtures";

// 验证实际选中的图片像素能覆盖高分屏，防止低清原图被重复压缩后冒充高清。
for (const [width, dpr] of [[1440, 2], [390, 3]]) {
  test(`${width}px / ${dpr}x 实拍原图像素充足并可放大查看`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({
      baseURL,
      viewport: { width, height: 1000 },
      deviceScaleFactor: dpr,
    });
    try {
      const page = await context.newPage();
      await publicVisitor(page);
      await page.goto("/");
      const panel = page.getByRole("tabpanel");
      for (const name of ["开始对话", "管理记忆", "更换形象"]) {
        await page.getByRole("tab", { name }).click();
        const image = panel.getByRole("img");
        await image.scrollIntoViewIfNeeded();
        const metrics = await image.evaluate(async (element: HTMLImageElement) => {
          await element.decode();
          const original = new Image();
          original.src = element.currentSrc;
          await original.decode();
          return {
            source: element.currentSrc,
            pixels: original.naturalWidth,
            displayed: element.getBoundingClientRect().width,
          };
        });
        expect(metrics.pixels, `${name} 实际像素不足`).toBeGreaterThanOrEqual(
          Math.ceil(metrics.displayed * dpr),
        );
        expect(new URL(metrics.source).pathname).toMatch(/-3x\.png$/);
        if (width === 1440) expect(metrics.displayed).toBeGreaterThan(1000);
        await expect(panel.getByRole("link", { name: "放大查看原图 ↗" }))
          .toHaveAttribute("href", new URL(metrics.source).pathname);
      }
      const [original] = await Promise.all([
        page.waitForEvent("popup"),
        panel.getByRole("link", { name: "放大查看原图 ↗" }).click(),
      ]);
      await original.waitForLoadState();
      await expect(original).toHaveURL(/client-appearance-v0\.8\.0-3x\.png$/);
    } finally {
      await context.close();
    }
  });
}
