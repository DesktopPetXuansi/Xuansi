import assert from "node:assert/strict";
import { test } from "node:test";
import { api, apiPage, ApiError } from "../src/lib/api.ts";
import { QueryClient } from "@tanstack/react-query";
import { redactChatCaches } from "../src/features/feedback/chat/chat-cache.ts";

// 全局账号数量属于分页响应，不能被通用信封校验静默丢弃。
test("分页读取保留全局匹配数量和下一页游标", async (context) => {
  context.mock.method(globalThis, "fetch", async () =>
    Response.json({ data: [], meta: { total: 28, nextCursor: "next-page" } }),
  );
  const result = await apiPage("/admin/users");
  assert.deepEqual(result.meta, { total: 28, nextCursor: "next-page" });
});

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

test("撤回同步清理个人与管理员的所有聊天和收件快照", async () => {
  const cache = new QueryClient();
  const original = {
    id: "target",
    title: "私有原文",
    description: "私有原文",
    contact: "private@example.invalid",
    diagnostics: {},
    githubIssueUrl: "",
  };
  const thread = {
    id: original.id,
    title: original.title,
    preview: "私有原文",
    lastMessage: { body: "私有原文" },
    unreadCount: 3,
    canReply: true,
  };
  const keys = [
    ["feedback-chat", "owner", false],
    ["feedback-chat", "owner", true],
    ["feedback-chat", "other", true],
  ];
  for (const key of keys)
    cache.setQueryData(key, { pages: [{ data: [thread] }], pageParams: [""] });
  cache.setQueryData(["admin-feedback", "NEW"], {
    pages: [{ data: [original] }],
    pageParams: [""],
  });
  await redactChatCaches(cache, "target", "WITHDRAWN");
  for (const [, data] of cache.getQueriesData({
    queryKey: ["feedback-chat"],
  })) {
    assert.equal(data.pages[0].data[0].unreadCount, 0);
    assert.equal(data.pages[0].data[0].canReply, false);
    assert.equal(JSON.stringify(data).includes("私有原文"), false);
  }
  const inbox = cache.getQueryData(["admin-feedback", "NEW"]);
  assert.equal(inbox.pages[0].data[0].description, "");
  assert.equal(inbox.pages[0].data[0].contact, "");
  cache.clear();
});

test("外部清理申请只清聊天快照，原收件正文仍供管理员清理", async () => {
  const cache = new QueryClient();
  cache.setQueryData(["feedback-chat", "owner", true], {
    pages: [
      {
        data: [
          {
            id: "target",
            preview: "私有消息",
            lastMessage: { body: "私有消息" },
            unreadCount: 2,
            canReply: true,
          },
        ],
      },
    ],
    pageParams: [""],
  });
  cache.setQueryData(["admin-feedback", "ALL"], {
    pages: [
      {
        data: [
          {
            id: "target",
            description: "公开原问题",
            contact: "private@example.invalid",
          },
        ],
      },
    ],
    pageParams: [""],
  });
  await redactChatCaches(cache, "target", "WITHDRAWAL_REQUESTED");
  assert.equal(
    JSON.stringify(
      cache.getQueryData(["feedback-chat", "owner", true]),
    ).includes("私有消息"),
    false,
  );
  assert.equal(
    cache.getQueryData(["admin-feedback", "ALL"]).pages[0].data[0].description,
    "公开原问题",
  );
  cache.clear();
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
