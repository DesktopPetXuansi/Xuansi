import type { Page } from "@playwright/test";
import type { Analytics } from "../src/features/admin-analytics-data";
import { adminVisitor } from "./admin-feedback-fixtures";

// 统计验收只使用合成数字，不读取生产访问记录。
export function sampleAnalytics(): Analytics {
  return {
    range: "7d",
    traffic: {
      visitors: 12,
      pageviews: 36,
      visits: 18,
      downloadClicks: 7,
      trend: [
        { date: "2026-10-28", pageviews: 16 },
        { date: "2026-10-29", pageviews: 20 },
      ],
    },
    downloads: {
      total: 25,
      versions: [
        {
          version: "v0.9.0",
          filename: "Xuansi-0.9.0-windows-x64-setup.exe",
          count: 3,
        },
        {
          version: "v0.8.0",
          filename: "Xuansi-0.8.0-windows-x64-setup.exe",
          count: 22,
        },
      ],
    },
  };
}

export async function adminAnalytics(page: Page) {
  await adminVisitor(page);
  const state = {
    data: sampleAnalytics(),
    reads: [] as string[],
    failing: false,
  };
  await page.route(/\/api\/v1\/admin\/analytics(?:\?.*)?$/, async (route) => {
    const range =
      new URL(route.request().url()).searchParams.get("range") ?? "7d";
    state.reads.push(range);
    if (state.failing)
      return route.fulfill({
        status: 503,
        json: {
          error: { code: "UNAVAILABLE", message: "统计服务暂时无法连接" },
        },
      });
    return route.fulfill({ json: { data: { ...state.data, range } } });
  });
  return state;
}
