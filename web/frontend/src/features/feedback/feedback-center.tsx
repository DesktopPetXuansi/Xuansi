"use client";

import { Button, Field, Heading, Notice } from "@/components/ui";
import { api, apiPage, ApiError } from "@/lib/api";
import type { Feedback, FeedbackModerationInput } from "@/lib/types";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { FeedbackItem, feedbackStatuses } from "./feedback-item";
import styles from "./feedback.module.css";

type Filter = Feedback["status"] | "ALL";
const filters = ["NEW", "IN_PROGRESS", "RESOLVED", "ALL"] as const;

export function FeedbackCenter() {
  const [filter, setFilter] = useState<Filter>("NEW");
  return (
    <>
      <Heading title="反馈中心">
        查看网站与客户端提交的问题和建议。先私有审核，获得作者许可后才可公开；联系方式始终仅管理员可见。
      </Heading>
      <div className={styles.toolbar}>
        <Field label="处理状态">
          <select
            aria-label="处理状态"
            value={filter}
            onChange={(event) => {
              const value = event.target.value;
              if (filters.some((item) => item === value)) {
                setFilter(value as Filter);
                console.debug("[反馈中心] 切换处理状态筛选");
              }
            }}
          >
            {filters.map((value) => (
              <option key={value} value={value}>
                {value === "ALL" ? "全部" : feedbackStatuses[value]}
              </option>
            ))}
          </select>
        </Field>
        <p>标记状态不会向用户发送回复。</p>
      </div>
      {/* 筛选重建列表，旧筛选请求即使迟到也不会覆盖新筛选。 */}
      <FeedbackList key={filter} filter={filter} />
    </>
  );
}

function FeedbackList({ filter }: { filter: Filter }) {
  const cache = useQueryClient();
  const queryKey = ["admin-feedback", filter] as const;
  const [pendingId, setPendingId] = useState<string>();
  const [actionError, setActionError] = useState<{
    id: string;
    error: unknown;
  }>();
  const [saved, setSaved] = useState("");
  const saving = useRef(false);
  const query = useInfiniteQuery({
    queryKey,
    initialPageParam: "",
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "20" });
      if (filter !== "ALL") params.set("status", filter);
      if (pageParam) params.set("cursor", pageParam);
      return apiPage<Feedback>(`/admin/feedback?${params}`);
    },
    getNextPageParam: (page) => page.meta?.nextCursor || undefined,
    retry: false,
  });
  async function change(
    item: Feedback,
    update: { status: Feedback["status"] } | FeedbackModerationInput,
  ) {
    if (saving.current) return;
    saving.current = true;
    setPendingId(item.id);
    setActionError(undefined);
    setSaved("");
    try {
      const updated = await api<Feedback>(
        `/admin/feedback/${item.id}${"decision" in update ? "/moderation" : ""}`,
        "decision" in update ? "POST" : "PATCH",
        update,
      );
      // 只在服务端确认后更新；失败保留正文和原状态，允许原地重试。
      cache.setQueryData<typeof query.data>(
        queryKey,
        (previous) =>
          previous && {
            ...previous,
            pages: previous.pages.map((page) => ({
              ...page,
              data: page.data
                .map((row) => (row.id === updated.id ? updated : row))
                .filter((row) => filter === "ALL" || row.status === filter),
            })),
          },
      );
      void cache.invalidateQueries({
        queryKey: ["admin-feedback"],
        refetchType: "none",
      });
      setSaved(
        "decision" in update
          ? "审核操作已保存。"
          : `已标记为${feedbackStatuses[updated.status]}。`,
      );
      console.debug("[反馈中心] 管理操作已保存");
    } catch (error) {
      setActionError({ id: item.id, error });
      console.warn("[反馈中心] 处理状态保存失败，保留原状态");
    } finally {
      saving.current = false;
      setPendingId(undefined);
    }
  }
  // 分页追加并按编号去重，加载失败保留已读内容，不展示反馈正文到日志。
  const accessDenied =
    query.error instanceof ApiError && [401, 403].includes(query.error.status);
  const items = accessDenied
    ? []
    : [
        ...new Map(
          query.data?.pages
            .flatMap((page) => page.data)
            .map((item) => [item.id, item]),
        ).values(),
      ];
  return (
    <section aria-label="反馈收件箱" aria-busy={query.isFetching}>
      {saved && <Notice>{saved}</Notice>}
      {query.isPending && <Notice>正在加载反馈…</Notice>}
      {query.error && (
        <div className={styles.failure}>
          <Notice error={query.error} />
          <Button
            className="secondary"
            disabled={query.isFetching}
            onClick={() => {
              console.debug("[反馈中心] 重试加载反馈");
              void (query.isFetchNextPageError
                ? query.fetchNextPage()
                : query.refetch());
            }}
          >
            重新加载
          </Button>
        </div>
      )}
      {!query.isPending && !query.error && items.length === 0 && (
        <Notice>
          {filter === "ALL"
            ? "暂时还没有收到反馈。"
            : "这个状态下暂时没有反馈。"}
        </Notice>
      )}
      <div className={styles.list}>
        {items.map((item) => (
          <FeedbackItem
            key={item.id}
            item={item}
            busy={pendingId !== undefined}
            saving={pendingId === item.id}
            error={
              actionError && actionError.id === item.id
                ? actionError.error
                : undefined
            }
            onChange={(status) => {
              void change(item, { status });
            }}
            onModerate={(decision) => void change(item, { decision })}
          />
        ))}
      </div>
      {query.hasNextPage && (
        <Button
          className="secondary"
          disabled={query.isFetching || pendingId !== undefined}
          onClick={() => {
            console.debug("[反馈中心] 加载下一页");
            void query.fetchNextPage();
          }}
        >
          {query.isFetchingNextPage ? "正在加载…" : "加载下一页"}
        </Button>
      )}
    </section>
  );
}
