import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../public/analytics-loader.js", import.meta.url),
  "utf8",
);
const websiteId = "94db1cb1-74f4-4a40-ad6c-962362670409";

// 使用隔离页面模拟运行时配置，不请求真实统计站点或生产服务。
async function load(config, { pathname = "/", failing = false } = {}) {
  const scripts = [];
  const warnings = [];
  const window = {
    location: { origin: "https://pet.example.com", hostname: "pet.example.com", pathname },
  };
  const document = {
    createElement: () => ({ dataset: {}, setAttribute(name, value) { this[name] = value; } }),
    head: { appendChild: (script) => scripts.push(script) },
  };
  const requests = [];
  vm.runInNewContext(source, {
    window,
    document,
    URL,
    AbortSignal,
    console: { warn: (value) => warnings.push(value) },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (failing) throw new Error("test unavailable");
      return { ok: true, json: async () => ({ data: config }) };
    },
  });
  await new Promise(setImmediate);
  return { window, scripts, warnings, requests };
}

test("配置未启用或无法读取时不加载外部脚本", async () => {
  const disabled = await load({ enabled: false, websiteId: null, scriptUrl: null });
  assert.equal(disabled.scripts.length, 0);
  assert.equal(disabled.warnings.length, 0);
  const offline = await load(null, { failing: true });
  assert.equal(offline.scripts.length, 0);
  assert.equal(offline.warnings.length, 1);
});

test("异步加载官方脚本并设置发送前过滤，配置请求不带会话", async () => {
  const result = await load({ enabled: true, websiteId, scriptUrl: "https://stats.example.com/script.js" });
  assert.equal(result.scripts.length, 1);
  const script = result.scripts[0];
  assert.equal(script.async, true);
  assert.equal(script.referrerPolicy, "no-referrer");
  assert.equal(script["data-website-id"], websiteId);
  assert.equal(script["data-before-send"], "xuansiAnalyticsBeforeSend");
  assert.equal(script["data-exclude-search"], "true");
  assert.equal(script["data-exclude-hash"], "true");
  assert.equal(result.requests[0].options.credentials, "omit");
});

test("拒绝不安全、同源或带查询参数的脚本地址", async () => {
  for (const scriptUrl of ["javascript:alert(1)", "http://stats.example.com/script.js", "https://pet.example.com/script.js", "https://stats.example.com/script.js?secret=token"]) {
    const result = await load({ enabled: true, websiteId, scriptUrl });
    assert.equal(result.scripts.length, 0);
  }
});

test("公开浏览量清除查询参数、片段、来源和账号字段", async () => {
  const { window } = await load({ enabled: true, websiteId, scriptUrl: "https://stats.example.com/script.js" });
  const clean = window.xuansiAnalyticsBeforeSend("event", {
    website: websiteId,
    url: "https://pet.example.com/download?email=private@example.com#token",
    referrer: "https://pet.example.com/feedback/manage?token=secret",
    title: "private user title",
    id: "account-id",
    hostname: "pet.example.com",
    language: "zh-CN",
    screen: "1920x1080",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(clean)), {
    website: websiteId,
    url: "/download",
    hostname: "pet.example.com",
    language: "zh-CN",
    screen: "1920x1080",
    referrer: "",
  });
});

test("SPA 切到私有页面即停止发送，返回公开页面继续统计", async () => {
  const { window } = await load({ enabled: true, websiteId, scriptUrl: "https://stats.example.com/script.js" });
  for (const path of ["/admin/analytics", "/dashboard", "/login", "/register", "/feedback/manage", "/docs/private-token", "/resources/private-id"]) {
    window.location.pathname = path;
    assert.equal(window.xuansiAnalyticsBeforeSend("event", { website: websiteId, url: path }), false);
  }
  window.location.pathname = "/docs/getting-started";
  assert.equal(window.xuansiAnalyticsBeforeSend("event", { website: websiteId, url: "/docs/getting-started?token=secret" }).url, "/docs/getting-started");
  assert.equal(window.xuansiAnalyticsBeforeSend("identify", { website: websiteId, url: "/" }), false);
});

test("只允许下载点击的版本信息，不传自定义个人数据", async () => {
  const { window } = await load({ enabled: true, websiteId, scriptUrl: "https://stats.example.com/script.js" });
  window.location.pathname = "/download";
  const clean = window.xuansiAnalyticsBeforeSend("event", {
    website: websiteId, url: "/download", name: "installer_download",
    data: { version: "0.9.0", platform: "windows-x64", email: "private@example.com" },
  });
  assert.deepEqual(JSON.parse(JSON.stringify(clean.data)), { version: "0.9.0", platform: "windows-x64" });
  assert.equal(window.xuansiAnalyticsBeforeSend("event", { website: websiteId, url: "/download", name: "private_event" }), false);
});
