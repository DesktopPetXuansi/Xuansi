import { expect, test } from "@playwright/test";
import { publicVisitor } from "./public-fixtures";

test("纸张主题在手机端保留可操作的控件", async ({ page }) => {
  await publicVisitor(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const route of ["/docs", "/resources"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toHaveCSS(
      "background-color",
      "rgb(245, 240, 232)",
    );
    const issues = await page.evaluate(() => {
      const nodes = document.querySelectorAll(
        ".site-header *, #main *, .site-footer *",
      );
      let effects = 0;
      let smallButtons = 0;
      for (const node of nodes) {
        if (!(node instanceof HTMLElement)) continue;
        const rect = node.getBoundingClientRect();
        if (!rect.width || !rect.height) continue;
        const style = getComputedStyle(node);
        if (
          style.backgroundImage.includes("gradient(") ||
          style.backdropFilter !== "none"
        )
          effects += 1;
        if (
          node.matches(
            'button, [role="button"], [data-slot="select-trigger"]',
          ) &&
          (rect.width < 44 || rect.height < 44)
        )
          smallButtons += 1;
      }
      return {
        effects,
        smallButtons,
        overflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    expect(issues, route).toEqual({
      effects: 0,
      smallButtons: 0,
      overflow: false,
    });
  }
  // 等待客户端完成初始化后再操作 Radix 下拉框。
  await page.waitForLoadState("networkidle");
  await page.getByRole("combobox", { name: "想找哪一种" }).click();
  const menu = page.locator('[data-slot="select-content"]');
  await expect(menu).toHaveCSS("background-color", "rgb(249, 245, 237)");
  await expect(menu).toHaveCSS("backdrop-filter", "none");
  await page.keyboard.press("Escape");
});
