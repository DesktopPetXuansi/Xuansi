import { expect, test } from "@playwright/test";
import { clientRelease } from "../src/lib/client-release";
import { publicVisitor } from "./public-fixtures";

test.beforeEach(async ({ page }) => {
  await publicVisitor(page);
});

test("首页按钮使用 shadcn 变体并保持铅笔与纸色对比", async ({ page }) => {
  await page.goto("/");
  const primary = page.getByRole("link", {
    name: "下载 Windows 客户端",
    exact: true,
  });
  await expect(primary).toHaveAttribute("data-slot", "button");
  await expect(primary).toHaveAttribute("data-variant", "default");
  await expect(primary).toHaveCSS("color", "rgb(245, 240, 232)");
  await expect(primary).toHaveCSS("background-color", "rgb(44, 44, 44)");
  await primary.hover();
  await expect(primary).toHaveCSS("color", "rgb(245, 240, 232)");

  const outline = page
    .locator(".library-promo")
    .getByRole("link", { name: "挑选形象", exact: true });
  await expect(outline).toHaveAttribute("data-slot", "button");
  await expect(outline).toHaveAttribute("data-variant", "outline");
  await expect(outline).toHaveCSS("background-color", "rgb(249, 245, 237)");
});

test("匿名下载保持官方地址，摘要复制成功与失败都有反馈", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/download");
  await expect(
    page.getByRole("link", { name: "下载 Windows 安装包", exact: true }),
  ).toHaveAttribute("href", clientRelease.downloadUrl);
  await expect(
    page.getByText("尚未进行代码签名", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("查看 SHA-256 校验与安装安全说明", { exact: true })
    .click();
  await page.getByRole("button", { name: "复制摘要", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已复制");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    clientRelease.sha256,
  );
  // 模拟浏览器拒绝剪贴板，只修改测试上下文，不更改产品代码或真实权限。
  await page.evaluate(() => {
    navigator.clipboard.writeText = async () => {
      throw new DOMException("测试拒绝", "NotAllowedError");
    };
  });
  await page.getByRole("button", { name: "复制摘要", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("复制失败");
  await expect(
    page.locator("code").filter({ hasText: clientRelease.sha256 }),
  ).toBeVisible();
});

test("平台记录失败可恢复，当前正式版始终可读", async ({ page }) => {
  let failing = true;
  await page.route("**/api/v1/client/releases?*", async (route) => {
    await route.fulfill(
      failing
        ? {
            status: 503,
            json: { error: { code: "UNAVAILABLE", message: "暂不可用" } },
          }
        : { json: { data: [] } },
    );
  });
  await page.goto("/changelog");
  await expect(
    page.getByRole("heading", {
      name: `玄司 ${clientRelease.version} · 先聊上第一句，遇到问题有指引。`,
    }),
  ).toBeVisible();
  const retry = page.getByRole("button", { name: "重新读取平台记录" });
  await expect(retry).toBeVisible();
  failing = false;
  await retry.click();
  await expect(
    page.getByText("平台暂未收录版本。可前往 GitHub 查看完整发行历史。"),
  ).toBeVisible();
  await expect(retry).toHaveCount(0);
});

test("资源接口失败后能重试，空库仍提供本地使用路径", async ({ page }) => {
  let failing = true;
  await page.route("**/api/v1/resources?*", async (route) => {
    await route.fulfill(
      failing
        ? {
            status: 503,
            json: { error: { code: "UNAVAILABLE", message: "测试连接失败" } },
          }
        : { json: { data: [], meta: { nextCursor: null } } },
    );
  });
  await page.goto("/resources");
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "测试连接失败",
  );
  await expect(
    page.getByRole("link", { name: "下载客户端", exact: true }).last(),
  ).toBeVisible();
  failing = false;
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "这里还没有已发布的资源" }),
  ).toBeVisible();
  await page.getByLabel("搜索名称").fill("不存在的演示资源");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "没有找到符合条件的资源" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(page.getByLabel("搜索名称")).toHaveValue("");
});

test("手机菜单关闭后归还焦点", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "展开主导航" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "展开主导航" })).toBeFocused();
  await expect(
    page.getByRole("button", { name: "展开主导航" }),
  ).toHaveAttribute("aria-expanded", "false");
});

test("首页不再显示客户端截图模块或请求其中的图片", async ({ page }) => {
  const screenshots: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/product/client-"))
      screenshots.push(request.url());
  });
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(
    page.getByRole("heading", { name: "看看玄司，用起来是什么样。" }),
  ).toHaveCount(0);
  await expect(page.locator("#product-preview")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "看看实际界面" })).toHaveCount(0);
  await expect(
    page.getByAltText("玄司角色：黑金服饰与长发的桌面伙伴"),
  ).toBeVisible();
  expect(screenshots).toEqual([]);
});
