import { expect, test } from "@playwright/test";
import type { Version } from "../src/lib/types";
import { adminVisitor } from "./admin-feedback-fixtures";
import { publicVisitor } from "./public-fixtures";
import { catalogResource } from "./resource-catalog-fixtures";

test("管理资源可选择就绪版本，也能恢复未选择状态", async ({ page }) => {
  await adminVisitor(page);
  const resource = catalogResource("7", "MODEL", "合成发布资源");
  const version = {
    id: "30000000-0000-4000-8000-000000000007",
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
  // 所有后台数据都由合成夹具提供，测试不会发布真实资源。
  await page.route("**/api/v1/admin/resources", (route) =>
    route.fulfill({ json: { data: [resource] } }),
  );
  await page.route(`**/api/v1/resources/${resource.id}/versions`, (route) =>
    route.fulfill({ json: { data: [version] } }),
  );
  await page.goto("/admin/resources");
  const select = page.getByRole("combobox", {
    name: "合成发布资源的发布版本",
    exact: true,
  });
  const publish = page.getByRole("button", {
    name: "发布公开资源",
    exact: true,
  });
  await expect(publish).toBeDisabled();
  await select.click();
  await page.getByRole("option", { name: "1.0.0", exact: true }).click();
  await expect(publish).toBeEnabled();
  await select.click();
  await page.getByRole("option", { name: "选择就绪版本", exact: true }).click();
  await expect(publish).toBeDisabled();
});

test("反馈管理下拉只切换当前浏览器中的合成记录", async ({ page }) => {
  await publicVisitor(page);
  const records = [1, 2].map((index) => {
    const id = `10000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
    return {
      id,
      idempotencyKey: id,
      managementToken: String(index).repeat(64),
    };
  });
  await page.addInitScript((items) => {
    localStorage.setItem("xuansi-feedback-management", JSON.stringify(items));
  }, records);
  await page.goto("/feedback/manage");
  const select = page.getByRole("combobox", {
    name: "本浏览器保存的反馈",
    exact: true,
  });
  await expect(select).toContainText("反馈 2");
  await select.click();
  await page.getByRole("option", { name: /反馈 1/ }).click();
  await expect(select).toContainText("反馈 1");
  await expect(page.getByLabel("专属管理链接", { exact: false })).toHaveValue(
    new RegExp(`id=${records[0].id}`),
  );
});
