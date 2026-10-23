import { expect, test } from "@playwright/test";
import { adminVisitor, sampleFeedback } from "./admin-feedback-fixtures";

test("后台默认可读正文和联系方式，直接处理且保存完成前锁定筛选", async ({
  page,
}) => {
  const item = sampleFeedback();
  await adminVisitor(page, { items: [item] });
  let releaseSave = () => {};
  const saveAllowed = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  const updates: unknown[] = [];
  await page.route(`**/api/v1/admin/feedback/${item.id}`, async (route) => {
    updates.push(route.request().postDataJSON());
    await saveAllowed;
    await route.fulfill({ json: { data: { ...item, status: "IN_PROGRESS" } } });
  });
  await page.goto("/admin/feedback");
  const card = page.getByRole("article", { name: item.title, exact: true });
  await expect(card.getByText(item.description, { exact: true })).toBeVisible();
  await expect(card.getByText(item.contact, { exact: true })).toBeVisible();
  await expect(card.getByText("查看反馈与处理", { exact: true })).toHaveCount(
    0,
  );
  await card.getByRole("button", { name: "开始处理", exact: true }).click();
  await expect.poll(() => updates.length).toBe(1);
  expect(updates[0]).toEqual({ status: "IN_PROGRESS" });
  const filters = page.getByRole("group", { name: "处理状态", exact: true });
  for (const label of ["待处理", "处理中", "已解决", "全部"]) {
    await expect(
      filters.getByRole("button", { name: label, exact: true }),
    ).toBeDisabled();
  }
  await expect(
    page.getByRole("button", { name: "刷新列表", exact: true }),
  ).toBeDisabled();
  await expect(card).toBeVisible();
  releaseSave();
  await expect(card).toHaveCount(0);
  await expect(
    page.getByText("已标记为处理中。", { exact: true }),
  ).toBeVisible();
});

test("刷新失败保留卡片，保存状态期间禁用错误区重新加载", async ({ page }) => {
  const item = sampleFeedback();
  await adminVisitor(page, { items: [item] });
  let releaseSave = () => {};
  const saveAllowed = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  const updates: unknown[] = [];
  await page.route(`**/api/v1/admin/feedback/${item.id}`, async (route) => {
    updates.push(route.request().postDataJSON());
    await saveAllowed;
    await route.fulfill({ json: { data: { ...item, status: "IN_PROGRESS" } } });
  });
  await page.goto("/admin/feedback");
  const card = page.getByRole("article", { name: item.title, exact: true });
  await expect(card).toBeVisible();
  // 仅拦截测试读取；503 保留已加载的卡片，复现读写同时重试的入口。
  await page.route(/\/api\/v1\/admin\/feedback\?/, async (route) => {
    await route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "测试刷新暂时失败" } },
    });
  });
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "测试刷新暂时失败",
  );
  await expect(card.getByText(item.description, { exact: true })).toBeVisible();
  const reload = page.getByRole("button", { name: "重新加载", exact: true });
  await expect(reload).toBeEnabled();
  await card.getByRole("button", { name: "开始处理", exact: true }).click();
  await expect.poll(() => updates.length).toBe(1);
  expect(updates[0]).toEqual({ status: "IN_PROGRESS" });
  await expect(reload).toBeDisabled();
  releaseSave();
  await expect(card).toHaveCount(0);
  await expect(
    page.getByText("已标记为处理中。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "刷新列表", exact: true }),
  ).toBeEnabled();
});

test("状态保存失败保留原文与原状态，并允许原地重试", async ({ page }) => {
  const item = sampleFeedback({
    title: "单行测试反馈",
    description: "单行测试反馈",
  });
  await adminVisitor(page, { items: [item] });
  const updates: unknown[] = [];
  await page.route(`**/api/v1/admin/feedback/${item.id}`, async (route) => {
    updates.push(route.request().postDataJSON());
    await route.fulfill(
      updates.length === 1
        ? {
            status: 503,
            json: { error: { code: "UNAVAILABLE", message: "测试保存中断" } },
          }
        : { json: { data: { ...item, status: "RESOLVED" } } },
    );
  });
  await page.goto("/admin/feedback");
  const card = page.getByRole("article", { name: item.title, exact: true });
  await expect(card.getByText(item.description, { exact: true })).toHaveCount(
    1,
  );
  await card.getByRole("button", { name: "标记已解决", exact: true }).click();
  await expect(card.getByRole("alert")).toHaveText("测试保存中断");
  await expect(card.getByText(item.description, { exact: true })).toBeVisible();
  await expect(card.getByText("待处理", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "标记已解决", exact: true }).click();
  await expect(card).toHaveCount(0);
  expect(updates).toEqual([{ status: "RESOLVED" }, { status: "RESOLVED" }]);
});

test("状态按钮筛选、刷新与下一页保持一致", async ({ page }) => {
  const initial = sampleFeedback();
  const progress = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000002",
    title: "正在处理的建议",
    status: "IN_PROGRESS",
  });
  const resolved = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000003",
    title: "已经解决的问题",
    status: "RESOLVED",
  });
  const fixture = await adminVisitor(page, {
    items: [initial, progress, resolved],
    pageSize: 1,
  });
  await page.goto("/admin/feedback");
  const filters = page.getByRole("group", { name: "处理状态", exact: true });
  await expect(
    filters.getByRole("button", { name: "待处理", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await filters.getByRole("button", { name: "处理中", exact: true }).click();
  await expect(
    page.getByRole("article", { name: progress.title, exact: true }),
  ).toBeVisible();
  await expect(
    filters.getByRole("button", { name: "处理中", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("article", { name: initial.title, exact: true }),
  ).toHaveCount(0);
  await filters.getByRole("button", { name: "已解决", exact: true }).click();
  await expect(
    page.getByRole("article", { name: resolved.title, exact: true }),
  ).toBeVisible();
  const beforeRefresh = fixture.listRequests.length;
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await expect
    .poll(() => fixture.listRequests.length)
    .toBeGreaterThan(beforeRefresh);
  expect(new URLSearchParams(fixture.listRequests.at(-1)).get("status")).toBe(
    "RESOLVED",
  );
  await filters.getByRole("button", { name: "全部", exact: true }).click();
  await expect(
    page.getByRole("article", { name: initial.title, exact: true }),
  ).toBeVisible();
  expect(new URLSearchParams(fixture.listRequests.at(-1)).has("status")).toBe(
    false,
  );
  await page.getByRole("button", { name: "加载下一页", exact: true }).click();
  await expect(
    page.getByRole("article", { name: initial.title, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("article", { name: progress.title, exact: true }),
  ).toBeVisible();
  expect(new URLSearchParams(fixture.listRequests.at(-1)).get("cursor")).toBe(
    "1",
  );
});

test("公开操作默认折叠且须有许可，撤回清理仍需明确确认", async ({ page }) => {
  const privateItem = sampleFeedback();
  const publicItem = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000002",
    title: "允许公开的建议",
    publicConsent: true,
  });
  const withdrawal = sampleFeedback({
    id: "10000000-0000-4000-8000-000000000003",
    title: "等待清理的反馈",
    publicConsent: true,
    moderationStatus: "WITHDRAWAL_REQUESTED",
    githubIssueUrl: "https://github.com/example/test/issues/1",
  });
  await adminVisitor(page, { items: [privateItem, publicItem, withdrawal] });
  const decisions: unknown[] = [];
  await page.route(
    `**/api/v1/admin/feedback/${withdrawal.id}/moderation`,
    async (route) => {
      decisions.push(route.request().postDataJSON());
      await route.fulfill({
        json: {
          data: {
            ...withdrawal,
            moderationStatus: "WITHDRAWN",
            description: "",
            contact: "",
          },
        },
      });
    },
  );
  await page.goto("/admin/feedback");
  const privateCard = page.getByRole("article", {
    name: privateItem.title,
    exact: true,
  });
  await privateCard.getByText("公开与其他操作", { exact: true }).click();
  await expect(
    privateCard.getByRole("button", {
      name: "审核通过并排队公开",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    privateCard.getByRole("button", { name: "未授权公开", exact: true }),
  ).toHaveCount(0);
  const publicCard = page.getByRole("article", {
    name: publicItem.title,
    exact: true,
  });
  await expect(
    publicCard.getByRole("button", { name: "审核通过并排队公开", exact: true }),
  ).not.toBeVisible();
  await publicCard.getByText("公开与其他操作", { exact: true }).click();
  await expect(
    publicCard.getByRole("button", { name: "审核通过并排队公开", exact: true }),
  ).toBeEnabled();
  const withdrawalCard = page.getByRole("article", {
    name: withdrawal.title,
    exact: true,
  });
  await expect(
    withdrawalCard.getByText("撤回请求：待清理公开内容", { exact: true }),
  ).toBeVisible();
  const confirmation = withdrawalCard.getByRole("button", {
    name: "确认清理并完成撤回",
    exact: true,
  });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toBeDisabled();
  expect(decisions).toHaveLength(0);
  await withdrawalCard
    .getByRole("checkbox", {
      name: "我已检查投递结果并在 GitHub 完成公开内容清理",
      exact: true,
    })
    .check();
  await confirmation.click();
  await expect.poll(() => decisions.length).toBe(1);
  expect(decisions[0]).toEqual({ decision: "CONFIRM_WITHDRAWAL" });
});

test("已解决反馈可继续处理或重开，处理中可移回待处理", async ({ page }) => {
  let item = sampleFeedback({ status: "RESOLVED" });
  await adminVisitor(page, { items: [item] });
  const updates: unknown[] = [];
  const nextStatuses = ["IN_PROGRESS", "NEW", "RESOLVED", "NEW"] as const;
  await page.route(`**/api/v1/admin/feedback/${item.id}`, async (route) => {
    const status = nextStatuses[updates.length];
    updates.push(route.request().postDataJSON());
    item = { ...item, status };
    await route.fulfill({ json: { data: item } });
  });
  await page.goto("/admin/feedback");
  await page
    .getByRole("group", { name: "处理状态", exact: true })
    .getByRole("button", { name: "全部", exact: true })
    .click();
  const card = page.getByRole("article", { name: item.title, exact: true });
  const actions = ["继续处理", "移回待处理", "标记已解决", "重新打开"];
  for (const [index, action] of actions.entries()) {
    await card.getByRole("button", { name: action, exact: true }).click();
    await expect.poll(() => updates.length).toBe(index + 1);
    await expect(
      page.getByRole("heading", { name: "反馈收件箱", exact: true }),
    ).toBeFocused();
    await expect(
      card.getByRole("button", {
        name: index === actions.length - 1 ? "开始处理" : actions[index + 1],
        exact: true,
      }),
    ).toBeEnabled();
  }
  expect(updates).toEqual(nextStatuses.map((status) => ({ status })));
});

test("取消主动刷新不能误清权限错误或恢复旧反馈缓存", async ({ page }) => {
  const item = sampleFeedback();
  await adminVisitor(page, { items: [item] });
  await page.route(`**/api/v1/admin/feedback/${item.id}`, async (route) => {
    await route.fulfill({
      status: 403,
      json: { error: { code: "FORBIDDEN", message: "测试权限已撤销" } },
    });
  });
  await page.goto("/admin/feedback");
  const card = page.getByRole("article", { name: item.title, exact: true });
  const filters = page.getByRole("group", { name: "处理状态", exact: true });
  await expect(card).toBeVisible();
  await filters.getByRole("button", { name: "全部", exact: true }).click();
  await expect(
    card.getByRole("button", { name: "开始处理", exact: true }),
  ).toBeEnabled();
  await card.getByRole("button", { name: "开始处理", exact: true }).click();
  const error = page.getByRole("main").getByRole("alert");
  await expect(error).toHaveText("测试权限已撤销");
  await expect(card).toHaveCount(0);

  let releaseRead = () => {};
  const readAllowed = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  let delayedReads = 0;
  await page.route(/\/api\/v1\/admin\/feedback\?/, async (route) => {
    const url = new URL(route.request().url());
    if (!url.searchParams.has("status")) {
      delayedReads += 1;
      await readAllowed;
    }
    await route.fulfill({ json: { data: [item], meta: { nextCursor: null } } });
  });
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await expect.poll(() => delayedReads).toBe(1);
  // 切换筛选取消原来的读取；新筛选的普通成功请求也不能代替主动恢复权限。
  await filters.getByRole("button", { name: "待处理", exact: true }).click();
  await expect(
    filters.getByRole("button", { name: "待处理", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "刷新列表", exact: true }),
  ).toBeEnabled();
  await expect(error).toHaveText("测试权限已撤销");
  await expect(card).toHaveCount(0);
  releaseRead();
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await expect(card).toBeVisible();
  await expect(error).toHaveCount(0);
});

for (const status of [401, 403]) {
  test(`保存收到${status}时隐藏正文，切换筛选不能恢复旧缓存`, async ({
    page,
  }) => {
    const item = sampleFeedback();
    await adminVisitor(page, { items: [item] });
    await page.route(`**/api/v1/admin/feedback/${item.id}`, async (route) => {
      await route.fulfill({
        status,
        json: {
          error: { code: "ACCESS_DENIED", message: "测试写入权限已失效" },
        },
      });
    });
    await page.goto("/admin/feedback");
    const card = page.getByRole("article", { name: item.title, exact: true });
    await expect(card).toBeVisible();
    const filters = page.getByRole("group", { name: "处理状态", exact: true });
    await filters.getByRole("button", { name: "全部", exact: true }).click();
    await expect(
      card.getByRole("button", { name: "开始处理", exact: true }),
    ).toBeEnabled();
    await card.getByRole("button", { name: "开始处理", exact: true }).click();
    const error = page.getByRole("main").getByRole("alert");
    await expect(error).toHaveText("测试写入权限已失效");
    await expect(card).toHaveCount(0);
    await expect(page.getByText(item.contact, { exact: true })).toHaveCount(0);
    await filters.getByRole("button", { name: "待处理", exact: true }).click();
    await expect(
      filters.getByRole("button", { name: "待处理", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(error).toHaveText("测试写入权限已失效");
    await expect(card).toHaveCount(0);
    // 恢复显示只能由用户主动重新读取成功触发，不依赖未失效的旧缓存。
    await page.getByRole("button", { name: "刷新列表", exact: true }).click();
    await expect(card).toBeVisible();
    await expect(error).toHaveCount(0);
  });

  test(`刷新收到${status}时清除已展示的管理员反馈`, async ({ page }) => {
    const item = sampleFeedback();
    await adminVisitor(page, { items: [item] });
    await page.goto("/admin/feedback");
    await expect(
      page.getByRole("article", { name: item.title, exact: true }),
    ).toBeVisible();
    // 模拟会话/权限在读取后失效，已缓存的私人正文也必须立即隐藏。
    await page.route(/\/api\/v1\/admin\/feedback\?/, async (route) => {
      await route.fulfill({
        status,
        json: {
          error: { code: "ACCESS_DENIED", message: "测试管理权限已失效" },
        },
      });
    });
    await page.getByRole("button", { name: "刷新列表", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toHaveText(
      "测试管理权限已失效",
    );
    await expect(page.getByRole("article")).toHaveCount(0);
  });
}

for (const role of ["USER", null] as const) {
  test(`${role ?? "匿名访客"}不能读取管理员反馈`, async ({ page }) => {
    const fixture = await adminVisitor(page, { role });
    await page.goto("/admin/feedback");
    await expect(
      page.getByRole("heading", {
        name: role === "USER" ? "你没有管理后台权限。" : "登录后，继续你的陪伴",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(0);
    expect(fixture.listRequests).toHaveLength(0);
  });
}
