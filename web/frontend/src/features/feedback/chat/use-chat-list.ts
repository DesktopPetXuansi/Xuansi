"use client";
import { api, ApiError } from "@/lib/api";
import type { FeedbackThreadPage } from "@/lib/types";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect } from "react";

export function useChatList(
  identity: string,
  admin: boolean,
  busy: boolean,
  onDenied: () => void,
) {
  const query = useInfiniteQuery({
    queryKey: ["feedback-chat", identity, admin],
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: "20" });
      if (pageParam) params.set("cursor", pageParam);
      return api<FeedbackThreadPage>(
        `${admin ? "/admin/feedback/conversations" : "/me/feedback"}?${params}`,
        "GET",
        undefined,
        true,
        { signal, expectedAccountId: admin ? undefined : identity },
      );
    },
    getNextPageParam: (page) => page.meta.nextCursor ?? undefined,
    retry: false,
    // 标签页隐藏、正在写入或读取更早页时暂停定时同步，避免旧快照覆盖操作。
    refetchInterval: busy ? false : 5000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: !busy,
  });
  const { refetch } = query;
  useEffect(() => {
    if (
      query.error instanceof ApiError &&
      ([401, 403].includes(query.error.status) ||
        query.error.code === "ACCOUNT_CHANGED")
    )
      onDenied();
  }, [query.error, onDenied]);
  useEffect(() => {
    const synchronize = () => {
      if (!document.hidden && !busy) void refetch();
    };
    document.addEventListener("visibilitychange", synchronize);
    return () => document.removeEventListener("visibilitychange", synchronize);
  }, [busy, refetch]);
  const threads = [
    ...new Map(
      query.data?.pages
        .flatMap((page) => page.data)
        .map((thread) => [thread.id, thread]),
    ).values(),
  ];
  return { ...query, threads };
}
