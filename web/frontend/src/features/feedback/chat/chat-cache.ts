import type { InfiniteData, QueryClient } from "@tanstack/react-query";
import type {
  Feedback,
  FeedbackManagement,
  FeedbackThreadPage,
} from "@/lib/types";

// 同一账号可以切换个人会话、管理员聊天与原收件页，撤回须同时清理这些快照。
export async function redactChatCaches(
  cache: QueryClient,
  id: string,
  moderationStatus: FeedbackManagement["moderationStatus"],
) {
  await Promise.all([
    cache.cancelQueries({ queryKey: ["feedback-chat"] }),
    cache.cancelQueries({ queryKey: ["admin-feedback"] }),
  ]);
  cache.setQueriesData<InfiniteData<FeedbackThreadPage>>(
    { queryKey: ["feedback-chat"] },
    (previous) =>
      previous && {
        ...previous,
        pages: previous.pages.map((page) => ({
          ...page,
          data: page.data.map((item) =>
            item.id === id
              ? {
                  ...item,
                  title:
                    moderationStatus === "WITHDRAWN"
                      ? "已撤回的反馈"
                      : "撤回处理中的反馈",
                  preview: "",
                  lastMessage: null,
                  unreadCount: 0,
                  canReply: false,
                  participant: { kind: "GUEST" as const, displayName: "访客" },
                  moderationStatus,
                }
              : item,
          ),
        })),
      },
  );
  cache.setQueriesData<InfiniteData<{ data: Feedback[] }>>(
    { queryKey: ["admin-feedback"] },
    (previous) =>
      previous && {
        ...previous,
        pages: previous.pages.map((page) => ({
          ...page,
          data: page.data.map((item) =>
            item.id === id
              ? {
                  ...item,
                  moderationStatus,
                  ...(moderationStatus === "WITHDRAWN"
                    ? {
                        title: "",
                        description: "",
                        contact: "",
                        diagnostics: null,
                        githubIssueUrl: "",
                      }
                    : {}),
                }
              : item,
          ),
        })),
      },
  );
  console.debug("[反馈聊天] 已同步清理撤回快照");
}
