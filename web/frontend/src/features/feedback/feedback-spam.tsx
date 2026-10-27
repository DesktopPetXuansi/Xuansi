"use client";

import { Button, Heading, Notice } from "@/components/ui";
import { api, apiPage, ApiError } from "@/lib/api";
import type { Feedback, FeedbackSpamClearReceipt } from "@/lib/types";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { clearFeedbackCaches, emptyFeedbackCaches } from "./feedback-cache";
import { FeedbackItem } from "./feedback-item";
import styles from "./feedback.module.css";

export function FeedbackSpam() {
  const cache = useQueryClient();
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState<unknown>();
  const [accessError, setAccessError] = useState<ApiError>();
  const [saved, setSaved] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const lock = useRef(false);
  const successfulReads = useRef(0);
  const query = useInfiniteQuery({
    queryKey: ["admin-feedback", "spam"],
    initialPageParam: "",
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams({ folder: "spam", limit: "20" });
      if (pageParam) params.set("cursor", pageParam);
      try {
        const page = await apiPage<Feedback>(`/admin/feedback?${params}`, {
          signal,
        });
        signal.throwIfAborted();
        successfulReads.current += 1;
        return page;
      } catch (error) {
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          setAccessError(error);
          emptyFeedbackCaches(cache);
        }
        throw error;
      }
    },
    getNextPageParam: (page) => page.meta?.nextCursor || undefined,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
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
  const busy = clearing || query.isFetching;

  async function reload(nextPage = false) {
    if (lock.current || query.isFetching) return;
    const previousReads = successfulReads.current;
    const result = await (nextPage ? query.fetchNextPage() : query.refetch());
    if (result.isSuccess && successfulReads.current > previousReads) {
      setAccessError((current) =>
        current === accessError ? undefined : current,
      );
      setClearError(undefined);
    }
    console.debug("[垃圾邮件] 已主动读取列表");
  }

  function confirmClear() {
    if (busy || accessDenied || !items.length) return;
    setClearError(undefined);
    setSaved("");
    dialog.current?.showModal();
  }

  async function clear() {
    if (lock.current || query.isFetching || accessDenied) return;
    lock.current = true;
    setClearing(true);
    setClearError(undefined);
    try {
      // 服务端按垃圾状态清空全部页；不把当前加载的编号当作清空范围。
      const receipt = await api<FeedbackSpamClearReceipt>(
        "/admin/feedback/spam",
        "DELETE",
      );
      await clearFeedbackCaches(cache, true);
      void cache.invalidateQueries({
        queryKey: ["feedback-chat"],
        predicate: (entry) => entry.queryKey[2] === true,
      });
      dialog.current?.close();
      setSaved(`已清空 ${receipt.clearedCount} 条垃圾邮件。`);
      listHeading.current?.focus();
      console.debug("[垃圾邮件] 清空成功", { count: receipt.clearedCount });
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        setAccessError(error);
        dialog.current?.close();
        await clearFeedbackCaches(cache);
      } else {
        setClearError(error);
      }
      console.warn("[垃圾邮件] 清空失败，可重新读取或重试");
    } finally {
      lock.current = false;
      setClearing(false);
    }
  }

  return (
    <>
      <Heading title="垃圾邮件">
        已标记为垃圾的反馈集中放在这里，不会出现在待处理列表中。
      </Heading>
      <section aria-label="垃圾邮件列表" aria-busy={busy}>
        <div className={styles.listHeader}>
          <h2 ref={listHeading} tabIndex={-1}>
            垃圾反馈
          </h2>
          <div className={styles.listActions}>
            <Button
              className="secondary"
              disabled={busy}
              onClick={() => void reload()}
            >
              {query.isFetching && !query.isPending ? "刷新中…" : "刷新列表"}
            </Button>
            <Button
              className="danger"
              disabled={busy || accessDenied || !items.length}
              onClick={confirmClear}
            >
              清空垃圾邮件
            </Button>
          </div>
        </div>
        {saved && <Notice>{saved}</Notice>}
        {query.isPending && <Notice>正在加载垃圾邮件…</Notice>}
        {listError && (
          <div className={styles.failure}>
            <Notice error={listError} />
            <Button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void reload(!accessDenied && query.isFetchNextPageError)
              }
            >
              重新加载
            </Button>
          </div>
        )}
        {!query.isPending && !listError && !items.length && (
          <Notice>垃圾邮件已清空。</Notice>
        )}
        <div className={styles.list}>
          {items.map((item) => (
            <FeedbackItem key={item.id} item={item} />
          ))}
        </div>
        {!accessDenied && query.hasNextPage && (
          <Button
            className="secondary"
            disabled={busy}
            onClick={() => void reload(true)}
          >
            {query.isFetchingNextPage ? "正在加载…" : "加载下一页"}
          </Button>
        )}
      </section>
      <dialog
        ref={dialog}
        className={styles.clearDialog}
        aria-labelledby="spam-clear-title"
        aria-describedby="spam-clear-description"
        onCancel={(event) => {
          if (lock.current) event.preventDefault();
        }}
      >
        <h2 id="spam-clear-title">清空垃圾邮件？</h2>
        <p id="spam-clear-description">
          将清空所有垃圾反馈的正文、联系方式和私有对话，包含尚未加载的页面。此操作无法恢复，正常反馈不会被清空。
        </p>
        {clearError !== undefined && <Notice error={clearError} />}
        <div className={styles.actions}>
          <Button
            className="secondary"
            disabled={clearing}
            onClick={() => dialog.current?.close()}
          >
            取消
          </Button>
          <Button
            className="danger"
            disabled={clearing}
            onClick={() => void clear()}
          >
            {clearing ? "正在清空…" : "确认清空"}
          </Button>
        </div>
      </dialog>
    </>
  );
}
