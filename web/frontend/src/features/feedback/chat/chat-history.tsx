"use client";
import { api, ApiError } from "@/lib/api";
import type { FeedbackConversation } from "@/lib/types";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import styles from "./chat.module.css";

export function ChatHistory({
  view,
  admin,
  accountId,
  busy,
  prependRevision,
  onUpdated,
  onDenied,
  onMissing,
}: {
  view: FeedbackConversation;
  admin: boolean;
  accountId: string;
  busy: boolean;
  prependRevision: number;
  onUpdated: () => void;
  onDenied: () => void;
  onMissing: () => void;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const latest = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true);
  const previousHeight = useRef(0);
  const previousPrepend = useRef(0);
  const acknowledged = useRef("");
  const [readError, setReadError] = useState(false);
  const [retryRead, setRetryRead] = useState(0);
  const watermark = view.messages.at(-1)?.id ?? view.id;
  const closed = ["WITHDRAWN", "WITHDRAWAL_REQUESTED"].includes(
    view.moderationStatus,
  );

  // 只在读者原本位于末尾时跟随新消息；向前翻页按高度差保持阅读位置。
  useLayoutEffect(() => {
    const element = scroll.current;
    if (!element) return;
    if (prependRevision !== previousPrepend.current)
      element.scrollTop += element.scrollHeight - previousHeight.current;
    else if (atEnd.current) element.scrollTop = element.scrollHeight;
    previousPrepend.current = prependRevision;
    previousHeight.current = element.scrollHeight;
  }, [view.messages, prependRevision]);

  useEffect(() => {
    const marker = latest.current;
    if (!marker || busy || closed || acknowledged.current === watermark) return;
    const controller = new AbortController();
    let visible = false;
    let pending = false;
    const confirmRead = async () => {
      if (
        !visible ||
        document.hidden ||
        pending ||
        acknowledged.current === watermark
      )
        return;
      pending = true;
      try {
        await api<void>(
          `${admin ? "/admin/feedback" : "/me/feedback"}/${view.id}/read`,
          "POST",
          { messageId: watermark },
          false,
          {
            signal: controller.signal,
            expectedAccountId: admin ? undefined : accountId,
          },
        );
        if (controller.signal.aborted) return;
        acknowledged.current = watermark;
        setReadError(false);
        onUpdated();
      } catch (problem) {
        if (controller.signal.aborted) return;
        setReadError(true);
        if (
          problem instanceof ApiError &&
          ([401, 403].includes(problem.status) ||
            problem.code === "ACCOUNT_CHANGED")
        )
          onDenied();
        else if (problem instanceof ApiError && problem.status === 404)
          onMissing();
        console.warn("[反馈聊天] 已读确认失败，保留未读提示");
      } finally {
        pending = false;
      }
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (visible) void confirmRead();
      },
      // 由真实页面视口判断可见性，内部滚动框在屏幕外时不能提前标为已读。
      { threshold: 1 },
    );
    observer.observe(marker);
    const resumed = () => {
      if (!document.hidden) void confirmRead();
    };
    document.addEventListener("visibilitychange", resumed);
    return () => {
      controller.abort();
      observer.disconnect();
      document.removeEventListener("visibilitychange", resumed);
    };
  }, [
    admin,
    accountId,
    busy,
    closed,
    watermark,
    view.id,
    onUpdated,
    onDenied,
    onMissing,
    retryRead,
  ]);

  return (
    <>
      <div
        ref={scroll}
        className={styles.history}
        role="log"
        aria-label="聊天记录"
        aria-live="polite"
        aria-relevant="additions text"
        onScroll={() => {
          const element = scroll.current;
          if (element)
            atEnd.current =
              element.scrollHeight - element.clientHeight - element.scrollTop <
              32;
        }}
      >
        <ol className={styles.messages}>
          {!closed && (
            <li className={!admin ? styles.own : undefined}>
              <div className={styles.messageMeta}>
                <strong>{view.submitterName || "访客"}</strong>
                {view.createdAt && (
                  <time dateTime={view.createdAt}>
                    {formatTime(view.createdAt)}
                  </time>
                )}
              </div>
              <p className={styles.bubble}>{view.description}</p>
              <small className={styles.muted}>最初的问题</small>
            </li>
          )}
          {view.messages.map((message) => (
            <li
              key={message.id}
              className={
                (message.authorRole === "ADMIN") === admin
                  ? styles.own
                  : undefined
              }
            >
              <div className={styles.messageMeta}>
                <strong>
                  {message.authorName ||
                    (message.authorRole === "ADMIN" ? "玄司开发者" : "访客")}
                </strong>
                <time dateTime={message.createdAt}>
                  {formatTime(message.createdAt)}
                </time>
              </div>
              <p className={styles.bubble}>{message.body}</p>
            </li>
          ))}
        </ol>
        <div ref={latest} className={styles.readMarker} aria-hidden="true" />
      </div>
      {readError && (
        <p className={styles.muted}>
          未能同步已读状态。
          <button
            className={styles.textButton}
            onClick={() => setRetryRead((value) => value + 1)}
          >
            重试已读确认
          </button>
        </p>
      )}
    </>
  );
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
