import { expect, test, type Page } from "@playwright/test";
import type { Release } from "../src/lib/types";
import { adminVisitor } from "./admin-feedback-fixtures";

const draft = {
  id: "60000000-0000-4000-8000-000000000001",
  version: "0.9.1",
  channel: "BETA",
  sourceCommit: "a".repeat(40),
  releaseNotes: "合成版本说明",
  publishedAt: null,
  artifacts: [],
} satisfies Release;

// 渠道的表单验证只请求合成响应，不创建、发布或编辑线上版本。
async function releaseAdmin(page: Page, editing = false) {
  await adminVisitor(page);
  const writes: { method: string; body: Record<string, unknown> }[] = [];
  await page.route(
    /\/api\/v1\/admin\/client-releases(?:\/[\da-f-]+)?$/,
    async (route) => {
      const method = route.request().method();
      if (method === "GET") {
        return route.fulfill({ json: { data: editing ? [draft] : [] } });
      }
      writes.push({
        method,
        body: route.request().postDataJSON() as Record<string, unknown>,
      });
      return route.fulfill({ json: { data: draft } });
    },
  );
  return writes;
}

for (const channel of ["STABLE", "BETA"] as const) {
  test(`版本渠道 ${channel} 通过 shadcn Select 正确提交`, async ({ page }) => {
    const writes = await releaseAdmin(page);
    await page.goto("/admin/releases");
    const selected = page.getByRole("combobox", { name: "渠道", exact: true });
    await expect(selected).toContainText("STABLE");
    if (channel === "BETA") {
      await selected.click();
      await page
        .getByRole("listbox")
        .getByRole("option", { name: "BETA", exact: true })
        .click();
    }
    await page.locator('input[name="version"]').fill("0.9.1");
    await page.locator('input[name="sourceCommit"]').fill("a".repeat(40));
    await page.locator('textarea[name="releaseNotes"]').fill("合成版本说明");
    await page
      .locator('input[name="downloadUrl"]')
      .fill("https://example.invalid/installer.exe");
    await page.locator('input[name="sha256"]').fill("b".repeat(64));
    await page.locator('input[name="bytes"]').fill("2048");
    await page.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("版本草稿已创建");
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ method: "POST", body: { channel } });
  });
}

test("编辑版本时渠道禁用，保存仅修改说明", async ({ page }) => {
  const writes = await releaseAdmin(page, true);
  await page.goto("/admin/releases");
  await page.getByRole("button", { name: "编辑草稿", exact: true }).click();
  const selected = page.getByRole("combobox", { name: "渠道", exact: true });
  await expect(selected).toBeDisabled();
  await expect(selected).toContainText("BETA");
  await page.locator('textarea[name="releaseNotes"]').fill("仅修改合成说明");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("版本说明已保存");
  expect(writes).toEqual([
    { method: "PATCH", body: { releaseNotes: "仅修改合成说明" } },
  ]);
});
