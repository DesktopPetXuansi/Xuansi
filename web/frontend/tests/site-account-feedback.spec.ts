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
  // 未确认的请求保留撤回入口，但不默认展开完整管理操作。
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
  ).toHaveAttribute("href", "/feedback/manage");
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

test("选填项默认折叠，用户主动填写联系方式并授权公开后才传输", async ({
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
  await section
    .getByText("联系方式与公开选项（选填）", { exact: true })
    .click();
  const consent = section.getByRole("checkbox");
  await expect(consent).not.toBeChecked();
  await expect(consent).toHaveAccessibleName(/GitHub/);
  await section
    .getByLabel(/^联系方式（选填）/)
    .fill("test-contact@example.invalid");
  await consent.check();
  await section
    .getByRole("textbox", { name: "问题或建议", exact: true })
    .fill("我愿意公开这条功能建议，但联系方式仅用于回复。");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    contact: "test-contact@example.invalid",
    publicConsent: true,
  });
});

test("浏览器禁止存储时仍展示完整管理链接，避免丢失撤回权限", async ({
  page,
}) => {
  // 模拟浏览器拒绝存储，不读取或修改任何真实用户凭据。
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
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
    .fill("浏览器禁止存储时，也需要可以自行撤回反馈。");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toBeVisible();
  const management = section.getByLabel("专属管理链接", { exact: false });
  await expect(management).toBeVisible();
  expect(requests).toHaveLength(1);
  const link = new URL(await management.inputValue());
  expect(link.pathname).toBe("/feedback/manage");
  const credentials = new URLSearchParams(link.hash.slice(1));
  expect(credentials.get("id")).toBe(requests[0].key);
  expect(credentials.get("key")).toBe(requests[0].key);
  expect(credentials.get("token")).toBe(requests[0].body.managementToken);
});
