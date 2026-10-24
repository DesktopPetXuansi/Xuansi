import { expect, test } from "@playwright/test";
import { publicVisitor } from "./public-fixtures";

test.beforeEach(async ({ page }) => {
  await publicVisitor(page);
});

test("登录注册入口保留原站内目标，账号用途与下载分离", async ({ page }) => {
  await page.goto("/login?returnTo=%2Fdocs%2Fchat");
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await page.getByRole("link", { name: "创建账号", exact: true }).click();
  await expect(page).toHaveURL(/\/register\?returnTo=%2Fdocs%2Fchat/);
  await expect(page.getByLabel("邮件验证码", { exact: true })).toBeVisible();
  await expect(page.getByLabel("设置密码", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "返回登录", exact: true }).click();
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fdocs%2Fchat/);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex, nofollow",
  );
  await expect(page.locator('link[rel="canonical"]')).toHaveCount(0);
});

test("匿名反馈默认私有，网络失败保留草稿与同一幂等请求", async ({ page }) => {
  const requests: { key: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/v1/feedback", async (route) => {
    const request = route.request();
    const key = request.headers()["idempotency-key"];
    requests.push({
      key,
      body: request.postDataJSON() as Record<string, unknown>,
    });
    await route.fulfill(
      requests.length === 1
        ? {
            status: 503,
            json: { error: { code: "UNAVAILABLE", message: "测试临时中断" } },
          }
        : {
            json: {
              data: {
                id: key,
                status: "NEW",
                createdAt: new Date().toISOString(),
              },
            },
          },
    );
  });
  await page.goto("/#feedback");
  const text = page.getByRole("textbox", { name: "问题或建议", exact: true });
  await text.fill("官网回归测试草稿，仅保存在拦截的测试请求中。");
  await expect(page.getByRole("checkbox")).not.toBeVisible();
  await page.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "测试临时中断",
  );
  await expect(text).toHaveValue(
    "官网回归测试草稿，仅保存在拦截的测试请求中。",
  );
  // 访客失败只保留当前内存中的发送意图，不创建管理凭据。
  await expect(page.getByRole("button", { name: "查看最新状态" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "撤回反馈", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("专属管理链接", { exact: false }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "重试这条反馈" }).click();
  await expect(
    page.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0].body.publicConsent).toBe(false);
  expect(requests[0].body).not.toHaveProperty("managementToken");
  await expect(text).toHaveCount(0);
});

test("匿名反馈只需填写正文，成功后显示简洁回执并可开始新草稿", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/v1/feedback", async (route) => {
    requests.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      json: {
        data: {
          id: route.request().headers()["idempotency-key"],
          status: "NEW",
          createdAt: new Date().toISOString(),
        },
      },
    });
  });
  await page.goto("/#feedback");
  const section = page.locator("#feedback");
  await expect(section.getByLabel(/^联系方式（选填）/)).not.toBeVisible();
  await expect(section.getByRole("checkbox")).not.toBeVisible();
  const text = section.getByRole("textbox", {
    name: "问题或建议",
    exact: true,
  });
  await text.fill("希望桌面窗口的拖动操作更顺畅。");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    description: "希望桌面窗口的拖动操作更顺畅。",
    contact: "",
    publicConsent: false,
  });
  await expect(text).toHaveCount(0);
  await expect(
    section.getByRole("link", { name: /^查看回复、补充或撤回/ }),
  ).toHaveCount(0);
  await expect(
    section.getByRole("button", { name: "查看最新状态" }),
  ).toHaveCount(0);
  await expect(
    section.getByRole("button", { name: "撤回反馈", exact: true }),
  ).toHaveCount(0);
  await expect(
    section.getByLabel("专属管理链接", { exact: false }),
  ).toHaveCount(0);
  await section.getByRole("button", { name: "再写一条", exact: true }).click();
  await expect(text).toHaveValue("");
  await expect(text).toBeFocused();
  await expect(
    section.getByRole("button", { name: "提交反馈", exact: true }),
  ).toBeVisible();
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toHaveCount(0);
});

test("访客反馈保持私有，不提供公开授权或管理凭据", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/v1/feedback", async (route) => {
    requests.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      json: {
        data: {
          id: route.request().headers()["idempotency-key"],
          status: "NEW",
          createdAt: new Date().toISOString(),
        },
      },
    });
  });
  await page.goto("/#feedback");
  const section = page.locator("#feedback");
  await expect(section.getByRole("checkbox")).toHaveCount(0);
  await section
    .locator("summary")
    .filter({ hasText: /^联系方式（选填）$/ })
    .click();
  await section
    .getByLabel(/^联系方式（选填）/)
    .fill("test-contact@example.invalid");
  await section
    .getByRole("textbox", { name: "问题或建议", exact: true })
    .fill("这是一条仅交给管理员的访客功能建议。");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    contact: "test-contact@example.invalid",
    publicConsent: false,
  });
});

test("登录状态尚未确认时不能按访客提交", async ({ page }) => {
  let finish: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let submissions = 0;
  await page.route("**/api/v1/me", async (route) => {
    await gate;
    return route.fulfill({
      status: 401,
      json: { error: { code: "UNAUTHORIZED", message: "请登录" } },
    });
  });
  await page.route("**/api/v1/feedback", async (route) => {
    submissions++;
    return route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "不应触发" } },
    });
  });
  await page.goto("/#feedback");
  const section = page.locator("#feedback");
  await expect(
    section.getByRole("button", { name: "提交反馈", exact: true }),
  ).toBeDisabled();
  expect(submissions).toBe(0);
  finish?.();
  await expect(
    section.getByRole("textbox", { name: "问题或建议", exact: true }),
  ).toBeEnabled();
});

test("登录状态读取失败不降级为访客，恢复前禁止提交", async ({ page }) => {
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "登录状态读取中断" } },
    }),
  );
  await page.goto("/#feedback");
  await expect(
    page
      .locator("#feedback")
      .getByRole("button", { name: "提交反馈", exact: true }),
  ).toBeDisabled();
  await expect(
    page.locator("#feedback").getByRole("button", { name: /重试.*登录状态/ }),
  ).toBeVisible();
});

test("访客成功不触碰本地存储，也不生成管理链接", async ({ page }) => {
  // 模拟浏览器拒绝存储，不读取或修改任何真实用户凭据。
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        document.documentElement.dataset.storageReads = String(
          Number(document.documentElement.dataset.storageReads ?? "0") + 1,
        );
        throw new DOMException("测试浏览器禁止存储", "SecurityError");
      },
    });
  });
  const requests: { key: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/v1/feedback", async (route) => {
    const key = route.request().headers()["idempotency-key"];
    requests.push({
      key,
      body: route.request().postDataJSON() as Record<string, unknown>,
    });
    await route.fulfill({
      json: {
        data: { id: key, status: "NEW", createdAt: new Date().toISOString() },
      },
    });
  });
  await page.goto("/#feedback");
  const section = page.locator("#feedback");
  await section
    .getByRole("textbox", { name: "问题或建议", exact: true })
    .fill("浏览器禁止存储时仍能提交一次性私有反馈。");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toBeVisible();
  await expect(
    section.getByLabel("专属管理链接", { exact: false }),
  ).toHaveCount(0);
  expect(requests).toHaveLength(1);
  expect(requests[0].body).not.toHaveProperty("managementToken");
  expect(
    await page.evaluate(() =>
      Number(document.documentElement.dataset.storageReads ?? "0"),
    ),
  ).toBe(0);
  await expect(
    section.getByRole("link", { name: /查看回复|补充或撤回/ }),
  ).toHaveCount(0);
});
