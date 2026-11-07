import { expect, test } from "@playwright/test";
import { catalogResource, resourceCatalog } from "./resource-catalog-fixtures";
import type { User, Version } from "../src/lib/types";

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
  const kind = page.getByRole("combobox", { name: "想找哪一种", exact: true });
  await kind.click();
  await page
    .getByRole("listbox")
    .getByRole("option", { name: "静态形象", exact: true })
    .click();
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
  await expect(kind).toContainText("静态形象");
  await expect(page.getByRole("link", { name: /合成静态形象/ })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("搜索名称", { exact: true })).toHaveValue("");
  await expect(kind).toContainText("静态形象");
  await kind.click();
  await page
    .getByRole("listbox")
    .getByRole("option", { name: "全部形象", exact: true })
    .click();
  await expect
    .poll(() => state.requests.at(-1)?.searchParams.get("kind"))
    .toBeNull();
  await expect(kind).toContainText("全部形象");
});

test("形象类型下拉支持键盘选择、Escape 回焦和清除筛选", async ({ page }) => {
  const state = await resourceCatalog(page);
  await page.goto("/resources");
  const kind = page.getByRole("combobox", { name: "想找哪一种", exact: true });
  await kind.focus();
  await kind.press("Enter");
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(kind).toBeFocused();
  await expect(kind).toContainText("全部形象");
  await kind.press("Enter");
  await expect(
    page
      .getByRole("listbox")
      .getByRole("option", { name: "全部形象", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("End");
  await expect(
    page
      .getByRole("listbox")
      .getByRole("option", { name: "透明动图", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect
    .poll(() => state.requests.at(-1)?.searchParams.get("kind"))
    .toBe("ANIMATION");
  await expect(kind).toContainText("透明动图");
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await expect(kind).toContainText("全部形象");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("kind"))
    .toBeNull();
});

test("收藏安装版本可固定并切回当前版本，内部选项值不进入请求", async ({
  page,
}) => {
  await resourceCatalog(page);
  const resource = catalogResource("9", "MODEL", "收藏下拉合成形象");
  const version = {
    id: "30000000-0000-4000-8000-000000000009",
    resourceId: resource.id,
    version: "1.0.0",
    entrypoint: "character.model3.json",
    validationStatus: "READY",
    compatibilityStatus: "UNTESTED",
    minimumClientVersion: "",
    packageBytes: 1024,
    packageSha256: "",
    validationReport: { errors: [], warnings: [] },
    dependencies: [],
    createdAt: "2026-10-28T00:00:00Z",
  } satisfies Version;
  const user = {
    id: resource.ownerId,
    email: "select-test@example.invalid",
    displayName: "下拉测试者",
    role: "USER",
    status: "ACTIVE",
    emailVerified: true,
    storage: { quotaBytes: 2147483648, usedBytes: 0, reservedBytes: 0 },
  } satisfies User;
  let pinnedVersionId: string | null = null;
  const writes: { pinnedVersionId: string | null }[] = [];
  // 所有数据来自合成夹具，不读写真实账号收藏。
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({ json: { data: user } }),
  );
  await page.route("**/api/v1/me/library", (route) =>
    route.fulfill({ json: { data: [{ resource, pinnedVersionId }] } }),
  );
  await page.route(`**/api/v1/resources/${resource.id}/versions`, (route) =>
    route.fulfill({ json: { data: [version] } }),
  );
  await page.route(`**/api/v1/me/library/${resource.id}`, async (route) => {
    expect(route.request().method()).toBe("PUT");
    const input = route.request().postDataJSON() as {
      pinnedVersionId: string | null;
    };
    writes.push(input);
    pinnedVersionId = input.pinnedVersionId;
    await route.fulfill({ json: { data: { resource, pinnedVersionId } } });
  });
  await page.goto("/dashboard/library");
  const versions = page.getByRole("combobox", {
    name: "安装版本",
    exact: true,
  });
  await expect(versions).toContainText("使用当前版本");
  await versions.click();
  await page
    .getByRole("listbox")
    .getByRole("option", { name: "1.0.0", exact: true })
    .click();
  await expect.poll(() => writes.at(-1)?.pinnedVersionId).toBe(version.id);
  await expect(versions).toContainText("1.0.0");
  await versions.click();
  await page
    .getByRole("listbox")
    .getByRole("option", { name: "使用当前版本", exact: true })
    .click();
  await expect.poll(() => writes.at(-1)?.pinnedVersionId).toBeNull();
  await expect(versions).toContainText("使用当前版本");
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
      await page.getByRole("main").screenshot({
        path: testInfo.outputPath(`catalog-${width}-2x.png`),
        animations: "disabled",
      });
    });
  }
});
