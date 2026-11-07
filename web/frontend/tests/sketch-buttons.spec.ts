import { expect, test } from "@playwright/test";
import { publicVisitor } from "./public-fixtures";
import { adminVisitor, sampleFeedback } from "./admin-feedback-fixtures";

test.beforeEach(async ({ page }) => {
  await publicVisitor(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("导航和正文中的按钮都使用铅笔边框与悬停反馈", async ({ page }) => {
  await page.goto("/docs", { waitUntil: "networkidle" });
  const navigation = page.getByRole("navigation", { name: "主导航" });
  const download = navigation.getByRole("link", { name: "下载客户端" });
  const link = navigation.getByRole("link", { name: "挑选形象" });
  const accordion = page.locator('[data-slot="accordion-trigger"]').first();

  for (const control of [download, link, accordion]) {
    await expect(control).toHaveCSS("border-top-style", "dashed");
    await expect(control).toHaveCSS("border-top-width", "2px");
  }
  await expect(download).toHaveCSS("background-color", "rgb(44, 44, 44)");
  await expect(download).toHaveCSS("color", "rgb(245, 240, 232)");
  await link.hover();
  await expect(link).toHaveCSS("background-color", "rgb(44, 44, 44)");
  await expect(link).toHaveCSS("color", "rgb(245, 240, 232)");
  await accordion.focus();
  await expect(accordion).toHaveCSS("outline-style", "dashed");
});

test("手机菜单和下拉按钮保留手绘样式与触控尺寸", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/resources", { waitUntil: "networkidle" });
  const toggle = page.getByRole("button", { name: "展开主导航" });
  const select = page.getByRole("combobox", { name: "想找哪一种" });
  for (const control of [toggle, select]) {
    await expect(control).toHaveCSS("border-top-style", "dashed");
    const box = await control.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
  await toggle.click();
  await expect(
    page.getByRole("navigation", { name: "主导航" }).getByRole("link", {
      name: "挑选形象",
    }),
  ).toHaveCSS("border-top-style", "dashed");
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
});

test("危险操作和弹窗按钮保留手绘边框与风险颜色", async ({ page }) => {
  await adminVisitor(page, {
    items: [sampleFeedback({ moderationStatus: "SPAM" })],
  });
  await page.goto("/admin/feedback/spam", { waitUntil: "networkidle" });
  const clear = page.getByRole("button", { name: "清空垃圾邮件", exact: true });
  await expect(clear).toBeEnabled();
  await expect(clear).toHaveCSS("border-top-style", "dashed");
  await expect(clear).toHaveCSS("background-color", "rgb(135, 57, 42)");
  await clear.click();
  const dialog = page.getByRole("dialog", { name: "清空垃圾邮件？" });
  const cancel = dialog.getByRole("button", { name: "取消", exact: true });
  const confirm = dialog.getByRole("button", { name: "确认清空", exact: true });
  await expect(cancel).toHaveCSS("border-top-style", "dashed");
  await expect(confirm).toHaveCSS("border-top-style", "dashed");
  await expect(confirm).toHaveCSS("background-color", "rgb(135, 57, 42)");
  await cancel.click();
  await expect(dialog).toBeHidden();
});
