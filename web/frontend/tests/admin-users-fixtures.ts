import type { Page } from "@playwright/test";
import type { User } from "../src/lib/types";
import { adminVisitor } from "./admin-feedback-fixtures";

// 管理员验收全部使用合成账号，任何写操作都止于隔离浏览器路由。
export async function adminUsers(page: Page) {
  await adminVisitor(page);
  const users: User[] = Array.from({ length: 42 }, (_, index) => ({
    id: `20000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    displayName:
      index === 0
        ? "当前管理员"
        : index === 41
          ? "旧页目标"
          : `用户${String(index).padStart(2, "0")}`,
    email:
      index === 41
        ? "last-page@example.invalid"
        : `page-user-${index}@example.invalid`,
    role: index === 0 ? "ADMIN" : "USER",
    status: index === 7 || index === 27 ? "DISABLED" : "ACTIVE",
    emailVerified: index % 2 === 0,
    storage: { quotaBytes: 0, usedBytes: 0, reservedBytes: 0 },
  }));
  const state = {
    users,
    reads: [] as URL[],
    writes: [] as { id: string; status: string }[],
    failing: false,
  };
  await page.route(/\/api\/v1\/admin\/users(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    state.reads.push(url);
    if (state.failing)
      return route.fulfill({
        status: 503,
        json: {
          error: { code: "UNAVAILABLE", message: "合成用户列表读取失败" },
        },
      });
    const keyword = (url.searchParams.get("search") ?? "").toLowerCase();
    const items = state.users.filter(
      (user) =>
        (!keyword ||
          `${user.displayName} ${user.email}`
            .toLowerCase()
            .includes(keyword)) &&
        (!url.searchParams.get("role") ||
          user.role === url.searchParams.get("role")) &&
        (!url.searchParams.get("status") ||
          user.status === url.searchParams.get("status")),
    );
    const offset = Number(url.searchParams.get("cursor") ?? 0);
    return route.fulfill({
      json: {
        data: items.slice(offset, offset + 20),
        meta: {
          total: items.length,
          nextCursor: offset + 20 < items.length ? String(offset + 20) : null,
        },
      },
    });
  });
  await page.route(/\/api\/v1\/admin\/users\/[\da-f-]+$/, async (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1) ?? "";
    const payload = route.request().postDataJSON() as {
      status: "ACTIVE" | "DISABLED";
    };
    state.writes.push({ id, status: payload.status });
    const item = state.users.find((user) => user.id === id);
    if (item) item.status = payload.status;
    return route.fulfill({ status: 204 });
  });
  return state;
}
