import { expect, test } from "@playwright/test";
import { resourceCatalog } from "./resource-catalog-fixtures";

test("挑选形象默认请求外观合集，动作与表情分组立即生效", async ({ page }) => {
  const state = await resourceCatalog(page);
  await page.goto("/resources");
  await expect
    .poll(() => state.requests.at(-1)?.searchParams.get("group"))
    .toBe("APPEARANCE");
  await expect(
    page.getByRole("heading", { name: "社区形象", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /合成 Live2D 形象/ }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /合成配套动作/ })).toHaveCount(0);
  await page.getByRole("button", { name: "动作与表情", exact: true }).click();
  await expect
    .poll(() => state.requests.at(-1)?.searchParams.get("group"))
    .toBe("ADDON");
  await expect(page.getByRole("link", { name: /合成配套动作/ })).toBeVisible();
  await expect(
    page.getByRole("link", { name: /合成 Live2D 形象/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "动作与表情", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("形象类型即时筛选，搜索与浏览器回退刷新保留正确条件", async ({ page }) => {
  const state = await resourceCatalog(page);
  await page.goto("/resources");
  await page.getByLabel("想找哪一种", { exact: true }).selectOption("IMAGE");
  await expect
    .poll(() => state.requests.at(-1)?.searchParams.get("kind"))
    .toBe("IMAGE");
  await expect(page).toHaveURL(/kind=IMAGE/);
  await page.getByLabel("搜索名称", { exact: true }).fill("静态");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("search"))
    .toBe("静态");
  await page.reload();
  await expect(page.getByLabel("搜索名称", { exact: true })).toHaveValue(
    "静态",
  );
  await expect(page.getByLabel("想找哪一种", { exact: true })).toHaveValue(
    "IMAGE",
  );
  await expect(page.getByRole("link", { name: /合成静态形象/ })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("搜索名称", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("想找哪一种", { exact: true })).toHaveValue(
    "IMAGE",
  );
});

test("社区形象按服务端分页，下一页和返回首页保留外观分组", async ({ page }) => {
  const state = await resourceCatalog(page);
  await page.goto("/resources");
  await expect(
    page.getByRole("link", { name: /合成 Live2D 形象/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: false }).click();
  await expect(page.getByRole("link", { name: /合成动图形象/ })).toBeVisible();
  expect(state.requests.at(-1)?.searchParams.get("group")).toBe("APPEARANCE");
  expect(state.requests.at(-1)?.searchParams.get("cursor")).toBe(
    "catalog-next-page",
  );
  await page.getByRole("button", { name: "返回第一页", exact: true }).click();
  await expect(
    page.getByRole("link", { name: /合成 Live2D 形象/ }),
  ).toBeVisible();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("cursor"))
    .toBeNull();
});

test("资源读取失败可重试，空社区仍展示真实自带形象", async ({ page }) => {
  const state = await resourceCatalog(page);
  state.failing = true;
  await page.goto("/resources");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "合成资源读取失败",
  );
  await expect(
    page.getByRole("img", { name: "客户端自带的玄司形象", exact: true }),
  ).toBeVisible();
  state.failing = false;
  state.items = [];
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "这里还没有已发布的资源" }),
  ).toBeVisible();
  await expect(
    page.getByText("网页负责浏览和下载，不会直接切换桌面上的形象。", {
      exact: false,
    }),
  ).toBeVisible();
});

test.describe("形象展示", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const width of [320, 390, 768, 1440]) {
    test(`${width}px形象卡片长名称及失效封面不撑宽页面`, async ({
      page,
    }, testInfo) => {
      const state = await resourceCatalog(page);
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.name));
      state.items[0].name = `形象${"长名称".repeat(24)}`;
      state.items[0].coverUrl = "/synthetic-missing-cover.png";
      state.items[1].coverUrl = null;
      await page.route("**/synthetic-missing-cover.png", (route) =>
        route.fulfill({ status: 404 }),
      );
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/resources");
      await expect(
        page.getByText("预览暂时不可用", { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText("作者暂未提供预览图", { exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
      await page
        .getByRole("main")
        .screenshot({
          path: testInfo.outputPath(`catalog-${width}-2x.png`),
          animations: "disabled",
        });
    });
  }
});
