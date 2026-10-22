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
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "测试临时中断",
  );
  await expect(text).toHaveValue(
    "官网回归测试草稿，仅保存在拦截的测试请求中。",
  );
  await page.getByRole("button", { name: "重试这条反馈" }).click();
  await expect(
    page.getByText(
      "已收到，反馈正在私有待审核。你可以撤回或保存专属管理链接。",
    ),
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0].body.publicConsent).toBe(false);
  await expect(text).toHaveValue("");
});
