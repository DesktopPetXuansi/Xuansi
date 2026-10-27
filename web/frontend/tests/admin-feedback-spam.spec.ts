import { expect, test } from "@playwright/test";
import { adminVisitor, sampleFeedback } from "./admin-feedback-fixtures";

const spam = () => sampleFeedback({ moderationStatus: "SPAM" });

test("标记垃圾成功后立即移出待处理，各筛选旧缓存也不能恢复它", async ({
  page,
}) => {
  const item = sampleFeedback();
  const fixture = await adminVisitor(page, { items: [item] });
  await page.route(
    `**/api/v1/admin/feedback/${item.id}/moderation`,
    async (route) => {
      expect(route.request().postDataJSON()).toEqual({ decision: "SPAM" });
      fixture.items[0] = { ...item, moderationStatus: "SPAM" };
      await route.fulfill({ json: { data: fixture.items[0] } });
    },
  );
  await page.goto("/admin/feedback");
  const filters = page.getByRole("group", { name: "处理状态", exact: true });
  await filters.getByRole("button", { name: "全部", exact: true }).click();
  await filters.getByRole("button", { name: "待处理", exact: true }).click();
  const card = page.getByRole("article", { name: item.title, exact: true });
  await card.getByText("公开与其他操作", { exact: true }).click();
  await card
    .getByRole("button", { name: "标记为垃圾反馈", exact: true })
    .click();
  await expect(card).toHaveCount(0);
  await expect(
    page.getByText("已移至垃圾邮件。", { exact: true }),
  ).toBeVisible();
  await filters.getByRole("button", { name: "全部", exact: true }).click();
  await expect(card).toHaveCount(0);
  await page.getByRole("link", { name: "垃圾邮件", exact: true }).click();
  await expect(card).toBeVisible();
});

test("垃圾邮件有独立菜单，仅展示垃圾反馈并支持跨页查看", async ({ page }) => {
  const first = spam();
  const second = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000002",
    title: "第二条垃圾反馈",
    moderationStatus: "SPAM",
    status: "RESOLVED",
  });
  const normal = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000003",
    title: "正常待处理反馈",
  });
  const fixture = await adminVisitor(page, {
    items: [first, second, normal],
    pageSize: 1,
  });
  await page.goto("/admin/feedback/spam");
  await expect(
    page.getByRole("heading", { name: "垃圾邮件", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "垃圾邮件", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("article", { name: first.title, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("article", { name: normal.title, exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "开始处理", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("group", { name: "处理状态", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "加载下一页", exact: true }).click();
  await expect(
    page.getByRole("article", { name: second.title, exact: true }),
  ).toBeVisible();
  for (const request of fixture.listRequests) {
    expect(new URLSearchParams(request).get("folder")).toBe("spam");
    expect(new URLSearchParams(request).has("status")).toBe(false);
  }
});

test("清空需确认，取消不请求，确认会清理全部页并保留正常反馈", async ({
  page,
}) => {
  const first = spam();
  const normal = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000003",
    title: "不可误删的正常反馈",
  });
  const fixture = await adminVisitor(page, {
    items: [
      first,
      sampleFeedback({
        id: "10000000-0000-4000-8000-000000000002",
        title: "尚未加载的垃圾反馈",
        moderationStatus: "SPAM",
      }),
      normal,
    ],
    pageSize: 1,
  });
  let clears = 0;
  await page.route("**/api/v1/admin/feedback/spam", async (route) => {
    expect(route.request().method()).toBe("DELETE");
    clears += 1;
    fixture.items.splice(0, fixture.items.length, normal);
    await route.fulfill({ json: { data: { clearedCount: 2 } } });
  });
  await page.goto("/admin/feedback/spam");
  const clear = page.getByRole("button", { name: "清空垃圾邮件", exact: true });
  await clear.click();
  await expect(
    page.getByRole("dialog", { name: "清空垃圾邮件？", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  expect(clears).toBe(0);
  await clear.click();
  await page.getByRole("button", { name: "确认清空", exact: true }).click();
  await expect.poll(() => clears).toBe(1);
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "加载下一页", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("已清空 2 条垃圾邮件。", { exact: true }),
  ).toBeVisible();
  await expect(clear).toBeDisabled();
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await expect(page.getByRole("article")).toHaveCount(0);
  await page.getByRole("link", { name: "收件与审核", exact: true }).click();
  await expect(
    page.getByRole("article", { name: normal.title, exact: true }),
  ).toBeVisible();
});

test("清空失败保留原文并可重试，提交中不能重复清空", async ({ page }) => {
  const item = spam();
  await adminVisitor(page, { items: [item] });
  let clears = 0;
  let releaseClear = () => {};
  const clearAllowed = new Promise<void>((resolve) => {
    releaseClear = resolve;
  });
  await page.route("**/api/v1/admin/feedback/spam", async (route) => {
    clears += 1;
    if (clears === 2) await clearAllowed;
    await route.fulfill(
      clears === 1
        ? {
            status: 503,
            json: { error: { code: "UNAVAILABLE", message: "测试清空失败" } },
          }
        : { json: { data: { clearedCount: 1 } } },
    );
  });
  await page.goto("/admin/feedback/spam");
  await page.getByRole("button", { name: "清空垃圾邮件", exact: true }).click();
  await page.getByRole("button", { name: "确认清空", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "测试清空失败",
  );
  await expect(
    page.getByRole("article", { name: item.title, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "确认清空", exact: true }).click();
  await expect.poll(() => clears).toBe(2);
  await expect(
    page.getByRole("button", { name: "正在清空…", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "取消", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "清空垃圾邮件？", exact: true }),
  ).toBeVisible();
  releaseClear();
  await expect(page.getByRole("article")).toHaveCount(0);
  expect(clears).toBe(2);
});

test("垃圾箱初次读取无权限时不保留加载状态，主动刷新成功后才恢复正文", async ({
  page,
}) => {
  const item = spam();
  await adminVisitor(page, { items: [item] });
  let allowed = false;
  await page.route(/\/api\/v1\/admin\/feedback\?/, async (route) => {
    await route.fulfill(
      allowed
        ? { json: { data: [item], meta: { nextCursor: null } } }
        : {
            status: 403,
            json: {
              error: { code: "FORBIDDEN", message: "测试垃圾箱读取权限不足" },
            },
          },
    );
  });
  await page.goto("/admin/feedback/spam");
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "测试垃圾箱读取权限不足",
  );
  await expect(
    page.getByText("正在加载垃圾邮件…", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  allowed = true;
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await expect(
    page.getByRole("article", { name: item.title, exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

for (const status of [401, 403]) {
  test(`清空收到 ${status} 时立即隐藏缓存正文与联系方式`, async ({ page }) => {
    const item = spam();
    await adminVisitor(page, { items: [item] });
    await page.route("**/api/v1/admin/feedback/spam", async (route) => {
      await route.fulfill({
        status,
        json: {
          error: { code: "ACCESS_DENIED", message: "测试垃圾箱权限已失效" },
        },
      });
    });
    await page.goto("/admin/feedback/spam");
    await page
      .getByRole("button", { name: "清空垃圾邮件", exact: true })
      .click();
    await page.getByRole("button", { name: "确认清空", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toHaveText(
      "测试垃圾箱权限已失效",
    );
    await expect(page.getByRole("article")).toHaveCount(0);
    await expect(page.getByText(item.contact, { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "清空垃圾邮件", exact: true }),
    ).toBeDisabled();
  });
}

for (const role of ["USER", null] as const) {
  test(`${role ?? "访客"}不能进入垃圾邮件菜单或发起垃圾箱读取`, async ({
    page,
  }) => {
    const fixture = await adminVisitor(page, { role });
    await page.goto("/admin/feedback/spam");
    await expect(
      page.getByRole("heading", {
        name: role === "USER" ? "你没有管理后台权限。" : "登录后，继续你的陪伴",
        exact: true,
      }),
    ).toBeVisible();
    expect(fixture.listRequests).toHaveLength(0);
    await expect(page.getByRole("article")).toHaveCount(0);
  });
}
