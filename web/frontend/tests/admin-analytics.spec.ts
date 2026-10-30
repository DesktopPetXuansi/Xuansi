import { expect, test } from "@playwright/test";
import { adminAnalytics } from "./admin-analytics-fixtures";
import { adminVisitor } from "./admin-feedback-fixtures";

test("管理员能区分访问指标和全来源安装包下载次数", async ({ page }) => {
  await adminAnalytics(page);
  await page.goto("/admin/analytics");
  await expect(
    page.getByRole("heading", { name: "访问统计", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("complementary", { name: "管理后台导航" })
      .getByRole("link", { name: "访问统计" }),
  ).toHaveAttribute("aria-current", "page");
  const metrics = page.getByRole("region", { name: "网站访问概览" });
  await expect(metrics.getByText("12", { exact: true })).toBeVisible();
  await expect(metrics.getByText("36", { exact: true })).toBeVisible();
  await expect(metrics.getByText("18", { exact: true })).toBeVisible();
  await expect(metrics.getByText("7", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "每日浏览量趋势" })).toBeVisible();
  await expect(page.getByText("25", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "GitHub 所有来源的累计下载次数，不代表下载人数或安装人数。",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByText("查看每日数据", { exact: true }).click();
  await expect(page.getByRole("row", { name: "2026-10-29 20" })).toBeVisible();
});

test("时间范围由按钮切换，安装包累计下载量保持独立", async ({ page }) => {
  const state = await adminAnalytics(page);
  await page.goto("/admin/analytics");
  await expect(page.getByText("25", { exact: true })).toBeVisible();
  for (const [label, range] of [
    ["近30天", "30d"],
    ["近90天", "90d"],
  ]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(
      page.getByRole("button", { name: label, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => state.reads.at(-1)).toBe(range);
    await expect(page.getByText("25", { exact: true })).toBeVisible();
  }
});

test("来源缺失和点击缺失不显示成零，其他来源仍可读", async ({ page }) => {
  const state = await adminAnalytics(page);
  state.data.traffic = null;
  await page.goto("/admin/analytics");
  await expect(
    page.getByText("访问数据暂不可用", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("25", { exact: true })).toBeVisible();
  state.data.traffic = {
    visitors: 0,
    pageviews: 0,
    visits: 0,
    downloadClicks: null,
    trend: [],
  };
  state.data.downloads = null;
  await page.getByRole("button", { name: "刷新统计", exact: true }).click();
  await expect(
    page.getByText("下载数据暂不可用", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("下载入口点击", { exact: true }).locator(".."),
  ).toContainText("暂不可用");
  await expect(
    page.getByText("所选时间暂无访问记录。", { exact: true }),
  ).toBeVisible();
});

test("统计接口失败后可以重试", async ({ page }) => {
  const state = await adminAnalytics(page);
  state.failing = true;
  await page.goto("/admin/analytics");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "统计服务暂时无法连接",
  );
  state.failing = false;
  await page.getByRole("button", { name: "重试读取统计", exact: true }).click();
  await expect(page.getByText("25", { exact: true })).toBeVisible();
});

test("每日浏览量均为零时趋势图显示真实峰值", async ({ page }) => {
  const state = await adminAnalytics(page);
  if (state.data.traffic)
    state.data.traffic.trend = [{ date: "2026-10-29", pageviews: 0 }];
  await page.goto("/admin/analytics");
  await expect(page.getByText("单位：次 · 北京时间 · 峰值 0")).toBeVisible();
});

for (const role of [null, "USER"] as const) {
  test(`${role === null ? "访客" : "普通账号"}不能请求管理员统计`, async ({
    page,
  }) => {
    await adminVisitor(page, { role });
    let reads = 0;
    await page.route("**/api/v1/admin/analytics?*", async (route) => {
      reads += 1;
      await route.fulfill({ json: { data: {} } });
    });
    await page.goto("/admin/analytics");
    await expect(
      page.getByRole("heading", {
        name: role === null ? "登录后，继续你的陪伴" : "你没有管理后台权限。",
      }),
    ).toBeVisible();
    expect(reads).toBe(0);
    await expect(
      page.getByRole("region", { name: "网站访问概览" }),
    ).toHaveCount(0);
  });
}

test("手机下长文件名和统计图不撑开页面", async ({ page }, testInfo) => {
  const state = await adminAnalytics(page);
  if (state.data.downloads)
    state.data.downloads.versions[0].filename = `${"long-filename-".repeat(16)}.exe`;
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/admin/analytics");
  await expect(page.getByText("25", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("analytics-mobile.png"),
    fullPage: true,
  });
});
