import type { Page } from "@playwright/test";
import type { Resource } from "../src/lib/types";
import { publicVisitor } from "./public-fixtures";

// 仅用于浏览器回归的合成资源，所有 API 都由测试截获，不写入公开资源库。
export function catalogResource(
  suffix: string,
  kind: Resource["kind"],
  name: string,
): Resource {
  return {
    id: `10000000-0000-4000-8000-${suffix.padStart(12, "0")}`,
    ownerId: "20000000-0000-4000-8000-000000000001",
    kind,
    name,
    description: "浏览器合成验收样本，并非真实社区发布。",
    author: "回归样本作者",
    license: "测试许可说明",
    source: "",
    tags: ["合成测试"],
    visibility: "PUBLIC",
    status: "ACTIVE",
    currentVersionId: null,
    coverUrl: "/brand/front.png",
    createdAt: "2026-10-24T00:00:00Z",
    updatedAt: "2026-10-24T00:00:00Z",
  };
}

export async function resourceCatalog(page: Page) {
  await publicVisitor(page);
  const state = {
    requests: [] as URL[],
    failing: false,
    items: [
      catalogResource("1", "MODEL", "合成 Live2D 形象"),
      catalogResource("2", "IMAGE", "合成静态形象"),
      catalogResource("3", "ANIMATION", "合成动图形象"),
      catalogResource("4", "MOTION", "合成配套动作"),
      catalogResource("5", "EXPRESSION", "合成配套表情"),
    ],
  };
  await page.route("**/api/v1/resources?*", async (route) => {
    const url = new URL(route.request().url());
    state.requests.push(url);
    if (state.failing)
      return route.fulfill({
        status: 503,
        json: { error: { code: "UNAVAILABLE", message: "合成资源读取失败" } },
      });
    const group = url.searchParams.get("group");
    const kinds =
      group === "APPEARANCE"
        ? ["MODEL", "IMAGE", "ANIMATION"]
        : group === "ADDON"
          ? ["MOTION", "EXPRESSION"]
          : null;
    const items = state.items.filter(
      (item) =>
        (!kinds || kinds.includes(item.kind)) &&
        (!url.searchParams.get("kind") ||
          item.kind === url.searchParams.get("kind")) &&
        (!url.searchParams.get("search") ||
          item.name.includes(url.searchParams.get("search") ?? "")),
    );
    const offset = url.searchParams.get("cursor") ? 2 : 0;
    return route.fulfill({
      json: {
        data: items.slice(offset, offset + 2),
        meta: {
          nextCursor: items.length > offset + 2 ? "catalog-next-page" : null,
        },
      },
    });
  });
  return state;
}
