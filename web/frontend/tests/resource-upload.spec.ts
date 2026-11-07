import { expect, test, type Page } from "@playwright/test";
import type { Resource, Upload, User, Version } from "../src/lib/types";
import { catalogResource } from "./resource-catalog-fixtures";
import { publicVisitor } from "./public-fixtures";

const resourceId = "10000000-0000-4000-8000-000000000001";
const versionId = "30000000-0000-4000-8000-000000000001";
const uploadId = "40000000-0000-4000-8000-000000000001";

// 所有上传均由浏览器拦截，字节不会送到真实存储，账号和文件也都是合成样本。
async function creator(
  page: Page,
  options: {
    verified?: boolean;
    kind?: Resource["kind"];
    failUpload?: boolean;
    loseCompletionResponse?: boolean;
    failCompletionOnce?: boolean;
    visibility?: Resource["visibility"];
  } = {},
) {
  await publicVisitor(page);
  const state = {
    resource: {
      ...catalogResource("1", options.kind ?? "MODEL", "合成上传形象"),
      visibility: options.visibility ?? "PRIVATE",
    } satisfies Resource,
    status: "CREATED" as Upload["status"],
    hasVersion: false,
    requests: [] as string[],
    completionKeys: [] as string[],
    resourceInput: undefined as Record<string, unknown> | undefined,
    versionInput: undefined as Record<string, unknown> | undefined,
  };
  const user = {
    id: state.resource.ownerId,
    email: "upload-test@example.invalid",
    displayName: "上传测试者",
    role: "USER",
    status: "ACTIVE",
    emailVerified: options.verified ?? true,
    storage: { quotaBytes: 2147483648, usedBytes: 0, reservedBytes: 0 },
  } satisfies User;
  const upload = () =>
    ({
      id: uploadId,
      versionId,
      status: state.status,
      expiresAt: "2099-01-01T00:00:00Z",
      method: "PUT",
      url: `/api/v1/uploads/${uploadId}/content`,
      headers: { "Content-Type": "application/octet-stream" },
      errorCode: null,
    }) satisfies Upload;
  const version = () =>
    ({
      id: versionId,
      resourceId,
      version: "1.0.0",
      entrypoint: "character/character.model3.json",
      validationStatus: state.status === "READY" ? "READY" : "VALIDATING",
      compatibilityStatus: "UNTESTED",
      minimumClientVersion: "",
      packageBytes: 2048,
      packageSha256: "",
      validationReport: { errors: [], warnings: [] },
      dependencies: [],
      createdAt: "2026-10-28T00:00:00Z",
    }) satisfies Version;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const method = request.method();
    if (path === "/me") return route.fulfill({ json: { data: user } });
    if (path === "/resources" && method === "POST") {
      state.requests.push("create-resource");
      state.resourceInput = request.postDataJSON() as Record<string, unknown>;
      return route.fulfill({ status: 201, json: { data: state.resource } });
    }
    if (path === `/resources/${resourceId}`) {
      if (method === "GET")
        return route.fulfill({ json: { data: state.resource } });
      if (method === "PATCH") {
        const body = request.postDataJSON() as { currentVersionId?: string };
        state.requests.push("select-version");
        state.resource.currentVersionId = body.currentVersionId ?? null;
        return route.fulfill({ json: { data: state.resource } });
      }
    }
    if (path === `/resources/${resourceId}/versions`) {
      if (method === "GET")
        return route.fulfill({
          json: { data: state.hasVersion ? [version()] : [] },
        });
      if (method === "POST") {
        state.requests.push("create-version");
        state.versionInput = request.postDataJSON() as Record<string, unknown>;
        state.hasVersion = true;
        return route.fulfill({
          status: 201,
          json: { data: { version: version(), upload: upload() } },
        });
      }
    }
    if (path === `/uploads/${uploadId}/content` && method === "PUT") {
      state.requests.push("put-file");
      if (options.failUpload) return route.fulfill({ status: 500 });
      state.status = "UPLOADED";
      return route.fulfill({ status: 204 });
    }
    if (path === `/uploads/${uploadId}/completion` && method === "POST") {
      state.requests.push("complete-upload");
      state.completionKeys.push(request.headers()["idempotency-key"] ?? "");
      if (options.loseCompletionResponse) {
        state.status = "READY";
        return route.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "合成响应中断" } },
        });
      }
      if (
        options.failCompletionOnce &&
        state.requests.filter((entry) => entry === "complete-upload").length ===
          1
      ) {
        return route.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "合成校验提交失败" } },
        });
      }
      state.status = "VALIDATING";
      return route.fulfill({ status: 202, json: { data: upload() } });
    }
    if (path === `/uploads/${uploadId}` && method === "GET")
      return route.fulfill({ json: { data: upload() } });
    return route.fallback();
  });
  return state;
}

function uploadForm(page: Page) {
  return page
    .locator("form")
    .filter({ has: page.locator('input[name="file"]') });
}

async function chooseModelAndSubmit(page: Page) {
  const form = uploadForm(page);
  await form.locator('input[name="file"]').setInputFiles({
    name: "synthetic-character.zip",
    mimeType: "application/zip",
    buffer: Buffer.alloc(2048),
  });
  await form.locator('input[name="version"]').fill("1.0.0");
  await form.getByRole("button", { name: /上传.*校验/ }).click();
}

test("新建作品先解释完整模型包和私有状态，再明确进入文件上传", async ({
  page,
}) => {
  const state = await creator(page);
  await page.goto("/dashboard/resources/new");
  const main = page.getByRole("main");
  await expect(main).toContainText(/zip/i);
  await expect(main).toContainText(".model3.json");
  await expect(main).toContainText(".moc3");
  await expect(main).toContainText("私有");
  await expect(main).toContainText("管理员");
  await page.locator('input[name="name"]').fill("合成上传形象");
  await page.locator('input[name="author"]').fill("合成作者");
  await page.locator('input[name="license"]').fill("仅用于浏览器验收");
  await page
    .getByRole("button", { name: "保存资料，选择文件", exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/dashboard/resources/${resourceId}#upload-version$`),
  );
  await expect(uploadForm(page)).toBeVisible();
  await expect(page.locator('[aria-current="step"]')).toContainText(
    "选择文件并上传",
  );
  expect(state.requests).toEqual(["create-resource"]);
  // 先选模型文件，编辑展示资料和可选封面不能挡在上传操作前面。
  const fileInput = page.locator('input[name="file"]');
  for (const selector of ['input[name="name"]', 'input[name="cover"]']) {
    expect(
      await fileInput.evaluate((element, targetSelector) => {
        const other = document.querySelector(targetSelector);
        return (
          other !== null &&
          !!(
            element.compareDocumentPosition(other) &
            Node.DOCUMENT_POSITION_FOLLOWING
          )
        );
      }, selector),
    ).toBe(true);
  }
});

test("未验证邮箱在创建前获得验证入口且不产生资源", async ({ page }) => {
  const state = await creator(page, { verified: false });
  await page.goto("/dashboard/resources/new");
  await expect(page.getByRole("main")).toContainText(/验证邮箱|邮箱验证/);
  await expect(
    page.getByRole("link", { name: /验证|发送验证邮件/ }),
  ).toHaveAttribute("href", /verify-email/);
  const save = page.getByRole("button", {
    name: "保存资料，选择文件",
    exact: true,
  });
  if (await save.count()) await expect(save).toBeDisabled();
  expect(state.requests).toEqual([]);
});

test("ZIP 上传按顺序传输并区分文件校验、当前版本和公开发布", async ({
  page,
}) => {
  const state = await creator(page);
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  const form = uploadForm(page);
  await form.locator('input[name="file"]').setInputFiles({
    name: "synthetic-character.zip",
    mimeType: "application/zip",
    buffer: Buffer.alloc(2048),
  });
  await expect(form).toContainText("synthetic-character.zip");
  await expect(form).toContainText(/2(?:\.0)?\s?KB/);
  await form.locator('input[name="version"]').fill("1.0.0");
  await form.getByRole("button", { name: /上传.*校验/ }).click();
  await expect
    .poll(() => state.requests)
    .toEqual(["create-version", "put-file", "complete-upload"]);
  expect(state.versionInput).toMatchObject({
    filename: "synthetic-character.zip",
    expectedBytes: 2048,
    version: "1.0.0",
  });
  await expect(form).toContainText(/后台.*校验|正在校验/);
  state.status = "READY";
  await expect(form).toContainText(/校验完成|校验通过/);
  await expect(
    page.getByRole("button", { name: "设为当前版本", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("main")).toContainText("当前版本");
  await expect(page.getByRole("main")).toContainText("私有");
  await expect(page.getByRole("main")).toContainText("管理员");
  await page.getByRole("button", { name: "设为当前版本", exact: true }).click();
  await expect.poll(() => state.resource.currentVersionId).toBe(versionId);
  await expect(
    page.getByRole("button", { name: "已是当前版本" }),
  ).toBeDisabled();
});

for (const status of ["CANCELLED", "EXPIRED"] as const) {
  test(`${status} 终态提供结束原因，不再声称后台校验中`, async ({ page }) => {
    const state = await creator(page);
    await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
    await chooseModelAndSubmit(page);
    await expect.poll(() => state.requests.at(-1)).toBe("complete-upload");
    state.status = status;
    const form = uploadForm(page);
    await expect(form).toContainText(status === "CANCELLED" ? "取消" : "过期");
    await expect(form).not.toContainText("正在后台校验");
  });
}

test("静态形象只展示图片要求，不让用户填写 Live2D 入口", async ({ page }) => {
  await creator(page, { kind: "IMAGE" });
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  const form = uploadForm(page);
  await expect(form.locator('input[name="file"]')).toHaveAttribute(
    "accept",
    /image\/png/,
  );
  await expect(form.locator('input[name="entrypoint"]')).toHaveCount(0);
  await expect(form).not.toContainText("Live2D 模型上传");
});

test("新建时切换作品类型会立即显示对应文件要求", async ({ page }) => {
  const state = await creator(page);
  await page.goto("/dashboard/resources/new");
  await page
    .getByRole("combobox", { name: "你要上传什么？", exact: true })
    .click();
  await page
    .getByRole("listbox")
    .getByRole("option", { name: "静态形象", exact: true })
    .click();
  await expect(
    page.getByRole("complementary", { name: "上传前准备" }),
  ).toContainText("PNG");
  await expect(
    page.getByRole("complementary", { name: "Live2D 上传前准备" }),
  ).toHaveCount(0);
  await page.locator('input[name="name"]').fill("合成静态形象");
  await page.locator('input[name="author"]').fill("合成作者");
  await page.locator('input[name="license"]').fill("仅用于浏览器验收");
  await page.getByRole("button", { name: "保存资料，选择文件" }).click();
  await expect.poll(() => state.resourceInput?.kind).toBe("IMAGE");
});

test("已有作品类型在下拉中可读且不可更改", async ({ page }) => {
  await creator(page, { kind: "IMAGE" });
  await page.goto(`/dashboard/resources/${resourceId}`);
  await page
    .getByRole("button", { name: "修改作品资料、封面和管理作品", exact: true })
    .click();
  const kind = page.getByRole("combobox", { name: "作品类型", exact: true });
  await expect(kind).toBeDisabled();
  await expect(kind).toContainText("静态形象");
});

test("Live2D 工程文件在创建上传任务前得到导出提示", async ({ page }) => {
  const state = await creator(page);
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  const form = uploadForm(page);
  await form.locator('input[name="file"]').setInputFiles({
    name: "character.cmo3",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("synthetic"),
  });
  await form.locator('input[name="version"]').fill("1.0.0");
  await form.getByRole("button", { name: /上传.*校验/ }).click();
  await expect(form.getByRole("alert")).toContainText(/\.zip.*导出/);
  expect(state.requests).toEqual([]);
});

test("文件传输失败后保留任务入口并说明重新上传需要新版本号", async ({
  page,
}) => {
  const state = await creator(page, { failUpload: true });
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  await chooseModelAndSubmit(page);
  const form = uploadForm(page);
  await expect(form.getByRole("alert")).toContainText(/任务已创建.*新的版本号/);
  await expect(
    form.getByRole("link", { name: "查看上传队列" }),
  ).toHaveAttribute("href", "/dashboard/uploads");
  expect(state.requests).toEqual(["create-version", "put-file"]);
});

test("为已公开作品上传新版本时不误称作品变成私有", async ({ page }) => {
  const state = await creator(page, { visibility: "PUBLIC" });
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  await chooseModelAndSubmit(page);
  await expect.poll(() => state.requests.at(-1)).toBe("complete-upload");
  state.status = "READY";
  await expect(uploadForm(page)).toContainText("上传不会改变作品的公开状态");
  await expect(page.getByRole("main")).not.toContainText("作品仍为私有");
});

test("完成响应丢失但服务端已校验完成时，以真实状态替代重传提示", async ({
  page,
}) => {
  const state = await creator(page, { loseCompletionResponse: true });
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  await chooseModelAndSubmit(page);
  await expect.poll(() => state.requests.at(-1)).toBe("complete-upload");
  const form = uploadForm(page);
  await expect(form).toContainText("文件校验已完成");
  await expect(form).not.toContainText("如需重新上传");
  await expect(form.getByRole("alert")).toHaveCount(0);
});

test("文件已传输但提交校验失败时，可重试同一任务而不重复上传", async ({
  page,
}) => {
  const state = await creator(page, { failCompletionOnce: true });
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  await chooseModelAndSubmit(page);
  const form = uploadForm(page);
  await expect(form.getByRole("alert")).toContainText("重试提交校验");
  await form.getByRole("button", { name: "重试提交校验" }).click();
  await expect
    .poll(() => state.requests)
    .toEqual([
      "create-version",
      "put-file",
      "complete-upload",
      "complete-upload",
    ]);
  expect(state.completionKeys[0]).not.toBe("");
  expect(state.completionKeys[1]).toBe(state.completionKeys[0]);
  await expect(form).toContainText("正在后台校验");
  await expect(form.getByRole("alert")).toHaveCount(0);
});

test("作品来源与标签收起后仍随资料提交", async ({ page }) => {
  const state = await creator(page);
  await page.goto("/dashboard/resources/new");
  await page.locator('input[name="name"]').fill("合成上传形象");
  await page.locator('input[name="author"]').fill("合成作者");
  await page.locator('input[name="license"]').fill("仅供测试");
  const options = page.getByRole("button", {
    name: "来源与标签（选填）",
    exact: true,
  });
  await options.click();
  await page
    .locator('input[name="source"]')
    .fill("https://example.invalid/art");
  await page.locator('input[name="tags"]').fill("国风, 合成样本");
  await options.click();
  await expect(page.locator('input[name="source"]')).toBeHidden();
  await page.getByRole("button", { name: "保存资料，选择文件" }).click();
  await expect
    .poll(() => state.resourceInput)
    .toMatchObject({
      source: "https://example.invalid/art",
      tags: ["国风", "合成样本"],
    });
});

test("上传高级设置收起后仍随版本提交", async ({ page }) => {
  const state = await creator(page);
  await page.goto(`/dashboard/resources/${resourceId}#upload-version`);
  const form = uploadForm(page);
  await form.locator('input[name="file"]').setInputFiles({
    name: "synthetic-character.zip",
    mimeType: "application/zip",
    buffer: Buffer.alloc(2048),
  });
  await form.locator('input[name="version"]').fill("1.0.0");
  const advanced = form.getByRole("button", {
    name: "高级设置（选填）",
    exact: true,
  });
  await advanced.click();
  await form.locator('input[name="minimumClientVersion"]').fill("0.9.0");
  await form
    .locator('input[name="entrypoint"]')
    .fill("model/character.model3.json");
  await advanced.click();
  await expect(form.locator('input[name="entrypoint"]')).toBeHidden();
  await form.getByRole("button", { name: "上传文件并校验" }).click();
  await expect
    .poll(() => state.versionInput)
    .toMatchObject({
      minimumClientVersion: "0.9.0",
      entrypoint: "model/character.model3.json",
    });
});

test("删除作品确认支持取消、失败重试和处理中阻止关闭", async ({ page }) => {
  await creator(page);
  let attempts = 0;
  let releaseDelete = () => {};
  const deleteAllowed = new Promise<void>((resolve) => {
    releaseDelete = resolve;
  });
  // 浏览器只处理合成请求，禁止触及真实资源。
  await page.route(`**/api/v1/resources/${resourceId}`, async (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    attempts += 1;
    if (attempts === 1) {
      return route.fulfill({
        status: 503,
        json: { error: { code: "UNAVAILABLE", message: "合成删除失败" } },
      });
    }
    await deleteAllowed;
    return route.fulfill({ status: 204 });
  });
  await page.goto(`/dashboard/resources/${resourceId}`);
  await page
    .getByRole("button", { name: "修改作品资料、封面和管理作品" })
    .click();
  await page.getByRole("button", { name: "删除作品" }).click();
  const dialog = page.getByRole("alertdialog", { name: "删除这个资源？" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "取消" }).click();
  expect(attempts).toBe(0);
  await page.getByRole("button", { name: "删除作品" }).click();
  await dialog.getByRole("button", { name: "确认删除" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("合成删除失败");
  await dialog.getByRole("button", { name: "确认删除" }).click();
  await expect.poll(() => attempts).toBe(2);
  await expect(
    dialog.getByRole("button", { name: "正在删除…" }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  releaseDelete();
  await expect(page).toHaveURL(/\/dashboard\/resources$/);
});
