import type { Page } from "@playwright/test";
import { adminVisitor } from "./admin-feedback-fixtures";

export const threadId = "10000000-0000-4000-8000-000000000001";
export const otherThreadId = "10000000-0000-4000-8000-000000000002";
export const messageId = "30000000-0000-4000-8000-000000000001";
export function chatMessage(body = "开发者的私有答复", id = messageId) {
  return {
    id,
    authorRole: "ADMIN",
    authorName: "玄司开发者",
    body,
    createdAt: "2026-10-24T01:00:00Z",
  };
}
export function chatThread(id = threadId, title = "账号测试问题") {
  return {
    id,
    title,
    preview: "最初的问题正文",
    status: "NEW",
    moderationStatus: "PENDING",
    participant: { kind: "ACCOUNT", displayName: "星河测试者" },
    createdAt: "2026-10-24T00:00:00Z",
    updatedAt: "2026-10-24T01:00:00Z",
    unreadCount: 1,
    canReply: true,
    lastMessage: chatMessage() as ReturnType<typeof chatMessage> | null,
  };
}
export function chatConversation(id = threadId) {
  return {
    id,
    title: id === threadId ? "账号测试问题" : "第二个问题",
    description: "最初的问题正文",
    status: "NEW",
    moderationStatus: "PENDING",
    canReply: true,
    participant: { kind: "ACCOUNT", displayName: "星河测试者" },
    submitterName: "提交时昵称",
    createdAt: "2026-10-24T00:00:00Z",
    unreadCount: 1,
    messages: [chatMessage()],
  };
}

// 所有请求都止于合成浏览器路由；fixture 不接触真实账户、邮件或反馈数据库。
export async function accountChat(page: Page, admin = false) {
  await adminVisitor(page, { role: admin ? "ADMIN" : "USER" });
  const state = {
    threads: [chatThread()],
    conversation: chatConversation(),
    reads: [] as { messageId: string }[],
    listRequests: 0,
    messageRequests: 0,
    readStatus: 204,
    messageStatus: 200,
  };
  const prefix = admin ? "/admin/feedback" : "/me/feedback";
  const listPath = admin ? `${prefix}/conversations` : prefix;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === listPath && request.method() === "GET") {
      state.listRequests++;
      return route.fulfill({
        json: { data: state.threads, meta: { nextCursor: null } },
      });
    }
    if (
      path.startsWith(`${prefix}/`) &&
      path.endsWith("/messages") &&
      request.method() === "GET"
    ) {
      state.messageRequests++;
      if (state.messageStatus !== 200)
        return route.fulfill({
          status: state.messageStatus,
          json: { error: { code: "DENIED", message: "合成权限错误" } },
        });
      const id = path.split("/").at(-2);
      return route.fulfill({
        json: {
          data: { ...state.conversation, id },
          meta: { nextCursor: null },
        },
      });
    }
    if (path.startsWith(`${prefix}/`) && path.endsWith("/read")) {
      state.reads.push(request.postDataJSON() as { messageId: string });
      return state.readStatus === 204
        ? route.fulfill({ status: 204 })
        : route.fulfill({
            status: state.readStatus,
            json: { error: { code: "UNAVAILABLE", message: "合成已读错误" } },
          });
    }
    return route.fallback();
  });
  return {
    state,
    prefix,
    path: admin ? "/admin/feedback/chat" : "/dashboard/feedback",
  };
}
