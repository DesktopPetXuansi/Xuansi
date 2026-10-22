import type { Page } from "@playwright/test";
import type { AuthConfig } from "../src/lib/types";

const authConfig = {
  password: { minLength: 12, maxLength: 128 },
  email: { mode: "SMTP", inboxUrl: null },
} satisfies AuthConfig;

// 只在测试浏览器拦截 API，避免真实注册、邮件发送或向生产提交反馈。
export async function publicVisitor(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/me") {
      await route.fulfill({
        status: 401,
        json: { error: { code: "UNAUTHORIZED", message: "请登录" } },
      });
    } else if (path === "/api/v1/auth/config") {
      await route.fulfill({ json: { data: authConfig } });
    } else if (path === "/api/v1/auth/csrf") {
      await route.fulfill({ json: { data: { token: "test-csrf" } } });
    } else if (path === "/api/v1/resources") {
      await route.fulfill({ json: { data: [], meta: { nextCursor: null } } });
    } else if (path === "/api/v1/client/releases") {
      await route.fulfill({ json: { data: [] } });
    } else {
      await route.fulfill({
        status: 404,
        json: {
          error: { code: "TEST_ROUTE_MISSING", message: "测试路由未配置" },
        },
      });
    }
  });
}
