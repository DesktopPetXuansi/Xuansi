import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { adminVisitor, sampleFeedback } from "./admin-feedback-fixtures";
import { publicVisitor } from "./public-fixtures";

const screenshots = resolve(
  process.env.MOBILE_SCREENSHOT_DIR ?? "../.runtime/screenshots/mobile-site",
);
const id = "10000000-0000-4000-8000-000000000001";
const longMessage = `手机测试说明 https://example.invalid/${"long-path/".repeat(30)}`;
const conversation = {
  id,
  title: "手机界面验收样本",
  description: longMessage,
  status: "NEW",
  moderationStatus: "PENDING",
  canReply: true,
  messages: [
    {
      id: "30000000-0000-4000-8000-000000000001",
      authorRole: "ADMIN",
      body: longMessage,
      createdAt: "2026-10-24T01:00:00Z",
    },
  ],
};

async function expectNoOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

// 合成样本和浏览器路由拦截覆盖全部 API，不读取真实后台、不发送邮件。
test.beforeAll(async () => {
  await mkdir(screenshots, { recursive: true });
});

for (const width of [320, 360, 390, 414, 768]) {
  test(`${width}px 手机公开入口、文本输入与导航`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await publicVisitor(page);
    await page.setViewportSize({ width, height: 844 });
    for (const path of [
      "/",
      "/download",
      "/resources",
      "/docs/chat",
      "/login",
      "/register",
    ]) {
      await page.goto(path, { waitUntil: "networkidle" });
      await expectNoOverflow(page);
      const smallInputs = await page
        .locator(
          'input:not([type="checkbox"]):not([type="radio"]), textarea, select',
        )
        .evaluateAll(
          (elements) =>
            elements.filter(
              (element) =>
                element.getBoundingClientRect().height > 0 &&
                parseFloat(getComputedStyle(element).fontSize) < 16,
            ).length,
        );
      expect(smallInputs, `${path} 编辑控件字号`).toBe(0);
    }
    if (width <= 640) {
      await page.getByRole("button", { name: "展开主导航" }).click();
      await page
        .getByRole("navigation", { name: "主导航", exact: true })
        .getByRole("link", { name: "下载客户端" })
        .click();
      await expect(page).toHaveURL(/\/download$/);
      await expect(
        page.getByRole("button", { name: "展开主导航" }),
      ).toHaveAttribute("aria-expanded", "false");
    }
    await page.screenshot({
      path: resolve(screenshots, `after-download-${width}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}

for (const width of [320, 390, 768]) {
  test(`${width}px 管理员长消息回复及横竖屏`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await adminVisitor(page, {
      items: [
        sampleFeedback({ title: conversation.title, description: longMessage }),
      ],
    });
    await page.route("**/api/v1/me", (route) =>
      route.fulfill({
        json: {
          data: {
            id,
            role: "ADMIN",
            email: "mobile-test@example.invalid",
            displayName: "手机验收测试用户昵称很长",
            status: "ACTIVE",
            emailVerified: true,
            storage: { quotaBytes: 0, usedBytes: 0, reservedBytes: 0 },
          },
        },
      }),
    );
    await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) =>
      route.fulfill({
        json:
          route.request().method() === "GET"
            ? { data: conversation, meta: { nextCursor: null } }
            : {
                data: {
                  message: {
                    ...conversation.messages[0],
                    id: "30000000-0000-4000-8000-000000000002",
                    body: "请尝试重新启动",
                  },
                  feedbackStatus: "NEW",
                },
              },
      }),
    );
    await page.goto("/admin/feedback");
    await page.getByRole("button", { name: "回复用户", exact: true }).click();
    await expect(page.getByRole("region", { name: "私有对话" })).toContainText(
      longMessage,
    );
    if (width <= 640) {
      const toggle = page.getByRole("button", { name: "展开主导航" });
      const brand = page.getByRole("link", { name: "玄司首页", exact: true });
      const [toggleBox, brandBox] = await Promise.all([
        toggle.boundingBox(),
        brand.boundingBox(),
      ]);
      expect(
        toggleBox && brandBox && Math.abs(toggleBox.y - brandBox.y) < 10,
      ).toBe(true);
      expect(
        await page
          .getByRole("complementary", { name: "管理后台导航" })
          .evaluate((element) => element.getBoundingClientRect().height),
      ).toBeLessThan(80);
    }
    await expectNoOverflow(page);
    await page.getByLabel("回复内容", { exact: true }).fill("请尝试重新启动");
    await page.getByRole("button", { name: "发送回复", exact: true }).click();
    await expect(page.getByText("回复已发送。", { exact: true })).toBeVisible();
    await page.screenshot({
      path: resolve(screenshots, `after-admin-${width}.png`),
      fullPage: true,
    });
    await page.setViewportSize({ width: 844, height: 390 });
    await expectNoOverflow(page);
    await expect(page.getByLabel("回复内容", { exact: true })).toBeVisible();
    if (width === 320) {
      await page.setViewportSize({ width, height: 844 });
      const sidebar = page.getByRole("complementary", {
        name: "管理后台导航",
      });
      const returnLink = sidebar.getByRole("link", {
        name: "返回我的桌宠",
        exact: true,
      });
      // 最末链接必须能进入可见滚动区域，并能通过键盘操作跳转。
      await returnLink.focus();
      expect(
        await sidebar.evaluate((element) => element.scrollLeft),
      ).toBeGreaterThan(0);
      await returnLink.press("Enter");
      await expect(page).toHaveURL(/\/dashboard$/);
    }
  });
}

test("320px 匿名管理链接查看长回复并发送补充", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await publicVisitor(page);
  await page.route(`**/api/v1/feedback/${id}/messages/query`, (route) =>
    route.fulfill({ json: { data: conversation, meta: { nextCursor: null } } }),
  );
  await page.route(`**/api/v1/feedback/${id}/messages`, (route) =>
    route.fulfill({
      json: {
        data: {
          message: {
            ...conversation.messages[0],
            authorRole: "USER",
            body: "重启后仍可复现",
          },
          feedbackStatus: "NEW",
        },
      },
    }),
  );
  await page.goto(
    `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
  );
  await page.getByRole("button", { name: "查看对话", exact: true }).click();
  await expect(page.getByRole("region", { name: "私有对话" })).toContainText(
    longMessage,
  );
  await page.getByLabel("补充说明", { exact: true }).fill("重启后仍可复现");
  await page.getByRole("button", { name: "发送补充", exact: true }).click();
  await expect(page.getByText("补充已发送。", { exact: true })).toBeVisible();
  await expectNoOverflow(page);
  await page.screenshot({
    path: resolve(screenshots, "after-anonymous-320.png"),
    fullPage: true,
  });
});
