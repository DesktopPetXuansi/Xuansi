"use client";

import { Button, Heading, Notice } from "@/components/ui";
import { api, apiPage, ApiError } from "@/lib/api";
import type { Feedback, FeedbackModerationInput } from "@/lib/types";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { FeedbackItem, feedbackStatuses } from "./feedback-item";
import styles from "./feedback.module.css";

type Filter = Feedback["status"] | "ALL";
const filters = ["NEW", "IN_PROGRESS", "RESOLVED", "ALL"] as const;

export function FeedbackCenter() {
  const [filter, setFilter] = useState<Filter>("NEW");
  const [working, setWorking] = useState(false);
  const [accessError, setAccessError] = useState<ApiError>();
  return (
    <>
      <Heading title="反馈中心">
        直接查看并处理反馈。公开到 GitHub 需单独审核，标记状态不会自动回复用户。
      </Heading>
      <div className={styles.toolbar}>
        <div className={styles.filters} role="group" aria-label="处理状态">
          {filters.map((value) => (
            <Button
              key={value}
              className={filter === value ? "" : "secondary"}
              aria-pressed={filter === value}
              disabled={working}
              onClick={() => {
                if (filter === value) return;
                setFilter(value);
                console.debug("[反馈中心] 切换处理状态筛选");
              }}
            >
              {value === "ALL" ? "全部" : feedbackStatuses[value]}
            </Button>
          ))}
        </div>
      </div>
      {/* 筛选重建列表，旧筛选请求即使迟到也不会覆盖新筛选。 */}
      <FeedbackList
        key={filter}
        filter={filter}
        accessError={accessError}
        onAccessError={setAccessError}
        onWorkingChange={setWorking}
      />
    </>
  );
}

function FeedbackList({
  filter,
  accessError,
  onAccessError,
  onWorkingChange,
}: {
  filter: Filter;
  accessError: ApiError | undefined;
  onAccessError: Dispatch<SetStateAction<ApiError | undefined>>;
  onWorkingChange: (working: boolean) => void;
}) {
  const cache = useQueryClient();
  const queryKey = ["admin-feedback", filter] as const;
  const [pendingId, setPendingId] = useState<string>();
  const [actionError, setActionError] = useState<{
    id: string;
    error: unknown;
  }>();
  const [saved, setSaved] = useState("");
  const saving = useRef(false);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const successfulReads = useRef(0);
  const query = useInfiniteQuery({
    queryKey,
    initialPageParam: "",
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: "20" });
      if (filter !== "ALL") params.set("status", filter);
      if (pageParam) params.set("cursor", pageParam);
      try {
        const page = await apiPage<Feedback>(`/admin/feedback?${params}`, {
          signal,
        });
        signal.throwIfAborted();
        successfulReads.current += 1;
        return page;
      } catch (error) {
        // 鉴权失败跨筛选保持隐藏，成功主动读取后才恢复正文。
        if (error instanceof ApiError && [401, 403].includes(error.status))
          onAccessError(error);
        throw error;
      }
    },
    getNextPageParam: (page) => page.meta?.nextCursor || undefined,
    retry: false,
    // 由筛选、翻页和刷新触发读取，避免窗口聚焦时的旧快照覆盖保存结果。
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  async function change(
    item: Feedback,
    update: { status: Feedback["status"] } | FeedbackModerationInput,
  ) {
    if (saving.current || query.isFetching) return;
    saving.current = true;
    setPendingId(item.id);
    onWorkingChange(true);
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
      // 状态按钮或卡片可能消失，把键盘焦点留在稳定的列表入口。
      listHeading.current?.focus();
      setSaved(
        "decision" in update
          ? "审核操作已保存。"
          : `已标记为${feedbackStatuses[updated.status]}。`,
      );
      console.debug("[反馈中心] 管理操作已保存");
    } catch (error) {
      setActionError({ id: item.id, error });
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        onAccessError(error);
        // 权限失效后清空各筛选的正文缓存，切换筛选也不能重新露出旧内容。
        await cache.cancelQueries({ queryKey: ["admin-feedback"] });
        cache.setQueriesData<typeof query.data>(
          { queryKey: ["admin-feedback"] },
          (previous) =>
            previous && {
              ...previous,
              pages: previous.pages.map((page) => ({ ...page, data: [] })),
            },
        );
        void cache.invalidateQueries({
          queryKey: ["admin-feedback"],
          refetchType: "none",
        });
      }
      console.warn("[反馈中心] 处理状态保存失败，保留原状态");
    } finally {
      saving.current = false;
      setPendingId(undefined);
      onWorkingChange(false);
    }
  }
  async function reload(nextPage = false) {
    if (saving.current || query.isFetching) return;
    console.debug("[反馈中心] 读取收件列表");
    const previousReads = successfulReads.current;
    const result = await (nextPage ? query.fetchNextPage() : query.refetch());
    // 取消读取可能回退旧的成功缓存；只接受实际读取完成，且不清除后来出现的鉴权错误。
    if (result.isSuccess && successfulReads.current > previousReads) {
      setActionError(undefined);
      onAccessError((current) =>
        current === accessError ? undefined : current,
      );
    }
  }
  // 分页追加并按编号去重，加载失败保留已读内容，不展示反馈正文到日志。
  const listError = accessError ?? query.error;
  const accessDenied =
    listError instanceof ApiError && [401, 403].includes(listError.status);
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
      <div className={styles.listHeader}>
        <h2 ref={listHeading} tabIndex={-1}>
          反馈收件箱
        </h2>
        <Button
          className="secondary"
          disabled={query.isFetching || pendingId !== undefined}
          onClick={() => void reload()}
        >
          {query.isFetching && !query.isPending ? "刷新中…" : "刷新列表"}
        </Button>
      </div>
      {saved && <Notice>{saved}</Notice>}
      {query.isPending && <Notice>正在加载反馈…</Notice>}
      {listError && (
        <div className={styles.failure}>
          <Notice error={listError} />
          <Button
            className="secondary"
            disabled={query.isFetching || pendingId !== undefined}
            onClick={() =>
              void reload(!accessDenied && query.isFetchNextPageError)
            }
          >
            重新加载
          </Button>
        </div>
      )}
      {!query.isPending && !listError && items.length === 0 && (
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
            busy={pendingId !== undefined || query.isFetching}
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
      {!accessDenied && query.hasNextPage && (
        <Button
          className="secondary"
          disabled={query.isFetching || pendingId !== undefined}
          onClick={() => void reload(true)}
        >
          {query.isFetchingNextPage ? "正在加载…" : "加载下一页"}
        </Button>
      )}
    </section>
  );
}
