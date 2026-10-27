import type { Page } from "@playwright/test";
import type { Feedback, User } from "../src/lib/types";
import { publicVisitor } from "./public-fixtures";

// 全部为本地测试样本，不读取真实管理员记录或联系信息。
export function sampleFeedback(overrides: Partial<Feedback> = {}): Feedback {
  return {
    id: "10000000-0000-4000-8000-000000000001",
    createdAt: "2026-10-23T01:00:00Z",
    updatedAt: "2026-10-23T01:00:00Z",
    status: "NEW",
    category: "BUG",
    title: "窗口拖动后位置没有保存",
    description:
      "窗口拖动后位置没有保存\n重新打开应用时，窗口回到了原来的位置。",
    contact: "tester@example.invalid",
    diagnostics: null,
    moderationStatus: "PENDING",
    publicConsent: false,
    githubIssueUrl: "",
    ...overrides,
  };
}

export async function adminVisitor(
  page: Page,
  options: {
    role?: User["role"] | null;
    items?: Feedback[];
    pageSize?: number;
  } = {},
) {
  await publicVisitor(page);
  const role = options.role === undefined ? "ADMIN" : options.role;
  const items = options.items ?? [sampleFeedback()];
  const listRequests: string[] = [];
  await page.route("**/api/v1/me", async (route) => {
    if (role === null) {
      await route.fulfill({
        status: 401,
        json: { error: { code: "UNAUTHORIZED", message: "请登录" } },
      });
      return;
    }
    const user = {
      id: "20000000-0000-4000-8000-000000000001",
      email: "admin-test@example.invalid",
      displayName: "测试用户",
      role,
      status: "ACTIVE",
      emailVerified: true,
      storage: { quotaBytes: 0, usedBytes: 0, reservedBytes: 0 },
    } satisfies User;
    await route.fulfill({ json: { data: user } });
  });
  await page.route(/\/api\/v1\/admin\/feedback(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    listRequests.push(url.search);
    const filtered = items.filter(
      (item) =>
        (url.searchParams.get("folder") === "spam"
          ? item.moderationStatus === "SPAM"
          : item.moderationStatus !== "SPAM") &&
        (!url.searchParams.has("status") ||
          item.status === url.searchParams.get("status")),
    );
    const offset = Number(url.searchParams.get("cursor") ?? "0");
    const size = options.pageSize ?? 20;
    await route.fulfill({
      json: {
        data: filtered.slice(offset, offset + size),
        meta: {
          nextCursor:
            offset + size < filtered.length ? String(offset + size) : null,
        },
      },
    });
  });
  return { items, listRequests };
}
