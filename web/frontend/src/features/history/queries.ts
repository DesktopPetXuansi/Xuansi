"use client";
import { apiPage } from "@/lib/api";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { HistoryEntry, HistoryKind } from "./types";

// 稳定游标由服务器生成；切换类别独立缓存，删除时一并失效首页摘要。
export function useHistory(kind: HistoryKind) {
  return useInfiniteQuery({
    queryKey: ["history", kind], initialPageParam: "",
    queryFn: ({ pageParam }) => apiPage<HistoryEntry>(`/me/history?kind=${kind}&limit=20${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    getNextPageParam: (last) => last.meta?.nextCursor || undefined,
  });
}
export function useRecentAppearances() {
  return useQuery({ queryKey: ["history", "recent"],
    queryFn: () => apiPage<HistoryEntry>("/me/history?kind=APPEARANCE&limit=4") });
}
