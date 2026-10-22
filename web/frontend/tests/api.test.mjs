import assert from "node:assert/strict";
import { test } from "node:test";
import { api, ApiError } from "../src/lib/api.ts";

// 请求不返回时，列表必须退出加载状态；这里使用短时限验证真实取消语义。
test("公开读取超时返回可重试错误", { timeout: 1000 }, async (context) => {
  context.mock.method(
    globalThis,
    "fetch",
    (_url, options) =>
      new Promise((_resolve, reject) => {
        options.signal?.addEventListener("abort", () =>
          reject(options.signal.reason),
        );
      }),
  );
  await assert.rejects(
    api("/resources", "GET", undefined, false, { timeoutMs: 20 }),
    (error) =>
      error instanceof ApiError &&
      error.status === 408 &&
      error.code === "REQUEST_TIMEOUT",
  );
});

test("筛选或切页取消请求时保留取消原因", async (context) => {
  const controller = new AbortController();
  const reason = new DOMException("已切换筛选", "AbortError");
  context.mock.method(globalThis, "fetch", (_url, options) => {
    assert.equal(options.signal.aborted, true);
    return Promise.reject(options.signal.reason);
  });
  controller.abort(reason);
  await assert.rejects(
    api("/resources", "GET", undefined, false, { signal: controller.signal }),
    (error) => error === reason,
  );
});

test("反馈写入保留 CSRF 与幂等编号，不施加读取超时", async (context) => {
  context.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.endsWith("/auth/csrf"))
      return Response.json({ data: { token: "test-csrf" } });
    assert.equal(options.method, "POST");
    assert.equal(options.headers["X-CSRF-Token"], "test-csrf");
    assert.equal(options.headers["Idempotency-Key"], "test-feedback-request");
    assert.equal(options.signal, undefined);
    return Response.json({ data: { id: "test-feedback-request" } });
  });
  const result = await api(
    "/feedback",
    "POST",
    { description: "测试草稿" },
    false,
    {
      idempotencyKey: "test-feedback-request",
    },
  );
  assert.deepEqual(result, { id: "test-feedback-request" });
});
