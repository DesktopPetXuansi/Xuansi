import { defineConfig } from "@playwright/test";

// 默认复用本地开发服务；最终验收可用环境变量指向独立生产构建。
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  outputDir: "../.runtime/test-results/public-site",
  workers: 2,
  timeout: 30000,
  expect: { timeout: 10000 },
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3010",
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome",
    locale: "zh-CN",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "pnpm exec next dev --hostname 127.0.0.1 --port 3010",
        url: "http://127.0.0.1:3010",
        reuseExistingServer: true,
        env: {
          CI: "1",
          NEXT_TELEMETRY_DISABLED: "1",
          SITE_URL: "http://127.0.0.1:3010",
        },
      },
});
