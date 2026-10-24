import { expect, test } from "@playwright/test";
import { adminUsers } from "./admin-users-fixtures";

test("用户管理能跨越20人限制，并返回上一页和第一页", async ({ page }) => {
  await adminUsers(page);
  await page.goto("/admin/users");
  await expect(page.getByText("共42个账号", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByRole("row", { name: /用户20/ })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByRole("row", { name: /旧页目标/ })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "下一页", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.getByRole("row", { name: /用户20/ })).toBeVisible();
  await page.getByRole("button", { name: "返回第一页", exact: true }).click();
  await expect(page.getByRole("row", { name: /当前管理员/ })).toBeVisible();
});

test("昵称邮箱搜索作用于全站账号，切换筛选重置分页", async ({ page }) => {
  const state = await adminUsers(page);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await page.getByLabel("搜索用户", { exact: true }).fill("LAST-PAGE");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByRole("row", { name: /旧页目标/ })).toBeVisible();
  expect(state.reads.at(-1)?.searchParams.get("cursor")).toBeNull();
  await expect(page.getByText("共1个账号", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await page.getByLabel("账号状态", { exact: true }).selectOption("DISABLED");
  await expect(page.getByText("共2个账号", { exact: true })).toBeVisible();
  await page.getByLabel("角色", { exact: true }).selectOption("ADMIN");
  await expect(
    page.getByRole("heading", { name: "没有符合条件的账号" }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(0);
});

test("停用先确认，当前管理员不可自停用，恢复账号仍可使用", async ({ page }) => {
  const state = await adminUsers(page);
  await page.goto("/admin/users");
  const current = page.getByRole("row", { name: /当前管理员/ });
  await expect(
    current.getByRole("button", { name: "当前账号", exact: true }),
  ).toBeDisabled();
  const row = page.getByRole("row", { name: /用户01/ });
  await row.getByRole("button", { name: "停用", exact: true }).click();
  expect(state.writes).toHaveLength(0);
  await row.getByRole("button", { name: "确认停用", exact: true }).click();
  await expect(
    row.getByRole("button", { name: "恢复", exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await row.getByRole("button", { name: "恢复", exact: true }).click();
  await expect(
    row.getByRole("button", { name: "停用", exact: true }),
  ).toBeVisible();
  expect(state.writes.map((write) => write.status)).toEqual([
    "DISABLED",
    "ACTIVE",
  ]);
});

test("用户列表失败可以重试，搜索不写入地址栏", async ({ page }) => {
  const state = await adminUsers(page);
  state.failing = true;
  await page.goto("/admin/users");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "合成用户列表读取失败",
  );
  state.failing = false;
  await page.getByRole("button", { name: "重试读取用户", exact: true }).click();
  await expect(page.getByText("共42个账号", { exact: true })).toBeVisible();
  await page
    .getByLabel("搜索用户", { exact: true })
    .fill("last-page@example.invalid");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByText("共1个账号", { exact: true })).toBeVisible();
  expect(new URL(page.url()).search).toBe("");
});

test.describe("用户列表布局", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const width of [320, 390, 768, 1440]) {
    test(`${width}px长昵称和邮箱保持可读且不横溢`, async ({
      page,
    }, testInfo) => {
      const state = await adminUsers(page);
      state.users.splice(4);
      state.users[1].displayName = "长昵称".repeat(35);
      state.users[1].email = `${"longaddress".repeat(8)}@example.invalid`;
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/admin/users");
      await expect(page.getByText("共4个账号", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("row", { name: /longaddress/ }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page
        .getByRole("main")
        .screenshot({
          path: testInfo.outputPath(`users-${width}-2x.png`),
          animations: "disabled",
        });
    });
  }
});
