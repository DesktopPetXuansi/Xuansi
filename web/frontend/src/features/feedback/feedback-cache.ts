import type { InfiniteData, QueryClient } from "@tanstack/react-query";
import type { Feedback, FeedbackThreadPage } from "@/lib/types";

// 标垃圾后的旧读取不能重新带回卡片；只改管理员聊天，不影响作者的私人列表。
export async function removeInboxFeedback(cache: QueryClient, id: string) {
  const adminChats = {
    queryKey: ["feedback-chat"],
    predicate: (query: { queryKey: readonly unknown[] }) =>
      query.queryKey[2] === true,
  };
  await Promise.all([
    cache.cancelQueries({ queryKey: ["admin-feedback"] }),
    cache.cancelQueries(adminChats),
  ]);
  cache.setQueriesData<InfiniteData<{ data: Feedback[] }>>(
    {
      queryKey: ["admin-feedback"],
      predicate: (query) => query.queryKey[1] !== "spam",
    },
    (previous) =>
      previous && {
        ...previous,
        pages: previous.pages.map((page) => ({
          ...page,
          data: page.data.filter((row) => row.id !== id),
        })),
      },
  );
  cache.setQueriesData<InfiniteData<FeedbackThreadPage>>(
    adminChats,
    (previous) =>
      previous && {
        ...previous,
        pages: previous.pages.map((page) => ({
          ...page,
          data: page.data.filter((row) => row.id !== id),
        })),
      },
  );
  await Promise.all([
    cache.invalidateQueries({
      queryKey: ["admin-feedback"],
      refetchType: "none",
    }),
    cache.invalidateQueries({ ...adminChats, refetchType: "none" }),
  ]);
}

// 权限失效或清空成功后去除正文及游标，避免翻页或切筛选重新显示旧快照。
export async function clearFeedbackCaches(
  cache: QueryClient,
  spamOnly = false,
) {
  await cache.cancelQueries({
    queryKey: ["admin-feedback"],
    predicate: (query) => !spamOnly || query.queryKey[1] === "spam",
  });
  emptyFeedbackCaches(cache, spamOnly);
}

// 读取自身失败时只擦除快照，让查询正常进入失败态；取消自身会回退到初次加载。
export function emptyFeedbackCaches(cache: QueryClient, spamOnly = false) {
  const selection = {
    queryKey: ["admin-feedback"],
    predicate: (query: { queryKey: readonly unknown[] }) =>
      !spamOnly || query.queryKey[1] === "spam",
  };
  cache.setQueriesData<
    InfiniteData<{ data: Feedback[]; meta?: { nextCursor?: string | null } }>
  >(
    selection,
    (previous) =>
      previous && {
        pages: [{ data: [], meta: { nextCursor: null } }],
        pageParams: [""],
      },
  );
  void cache.invalidateQueries({ ...selection, refetchType: "none" });
}
