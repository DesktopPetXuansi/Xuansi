"use client";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { useQuery, type QueryClient } from "@tanstack/react-query";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: async () => {
    try { return await api<User>("/me"); }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  }});
}
// 账号切换先取消旧查询，避免晚到的个人响应写回新账号缓存。
export async function replaceSession(cache: QueryClient, signedIn: boolean) {
  await cache.cancelQueries();
  cache.clear();
  cache.setQueryData<User | null>(["me"], signedIn ? await api<User>("/me") : null);
  console.debug("[账号] 身份与个人缓存已更新");
}
