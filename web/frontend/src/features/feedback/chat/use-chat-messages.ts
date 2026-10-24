"use client";
import { api, ApiError } from "@/lib/api";
import type {
  FeedbackConversation,
  FeedbackConversationResponse,
  FeedbackMessageReceipt,
  FeedbackManagement,
} from "@/lib/types";
import { useCallback, useEffect, useRef, useState } from "react";
import { mergeMessages } from "./chat-messages";

type Intent = { body: string; key: string; resolve: boolean };
export type ChatAccess = {
  id: string;
  admin: boolean;
  accountId: string;
  version: string;
  onDenied: () => void;
  onMissing: () => void;
  onUpdated: () => void;
  onBusy: (busy: boolean) => void;
  onRedacted: (
    moderation: FeedbackManagement["moderationStatus"],
  ) => Promise<void>;
};

// 一次挂载只属于一个账号和会话；取消和代次共同阻止迟到正文复活。
export function useChatMessages({
  id,
  admin,
  accountId,
  version,
  onDenied,
  onMissing,
  onUpdated,
  onBusy,
  onRedacted,
}: ChatAccess) {
  const [view, setView] = useState<FeedbackConversation>();
  const [cursor, setCursor] = useState<string | null>();
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [error, setError] = useState<unknown>();
  const [draft, setDraft] = useState("");
  const [intent, setIntent] = useState<Intent>();
  const [sent, setSent] = useState(false);
  const controller = useRef<AbortController | undefined>(undefined);
  const epoch = useRef(0);
  const lock = useRef(false);
  const mounted = useRef(true);
  const nextCursor = useRef<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const focusPending = useRef(false);
  const [prependRevision, setPrependRevision] = useState(0);
  const paging = useRef(false);
  const loadedEarlier = useRef(false);
  const redactedStatus = useRef("");
  const base = admin ? `/admin/feedback/${id}` : `/me/feedback/${id}`;

  const failure = useCallback(
    (problem: unknown) => {
      setError(problem);
      if (!(problem instanceof ApiError)) return;
      if (
        [401, 403, 404].includes(problem.status) ||
        problem.code === "ACCOUNT_CHANGED"
      ) {
        epoch.current++;
        controller.current?.abort();
        setView(undefined);
        setDraft("");
        setIntent(undefined);
        setCursor(null);
        if (problem.status === 404) onMissing();
        else onDenied();
      }
    },
    [onDenied, onMissing],
  );

  const load = useCallback(
    async (earlier = false) => {
      if (lock.current || paging.current) return;
      controller.current?.abort();
      const active = new AbortController();
      controller.current = active;
      const generation = ++epoch.current;
      const params = new URLSearchParams({ limit: "20" });
      if (earlier && nextCursor.current)
        params.set("cursor", nextCursor.current);
      setLoading(true);
      setError(undefined);
      if (earlier) {
        paging.current = true;
        onBusy(true);
      }
      try {
        const result = await api<FeedbackConversationResponse>(
          `${base}/messages?${params}`,
          "GET",
          undefined,
          true,
          {
            signal: active.signal,
            expectedAccountId: admin ? undefined : accountId,
          },
        );
        if (
          !mounted.current ||
          generation !== epoch.current ||
          active.signal.aborted
        )
          return;
        const closed = ["WITHDRAWN", "WITHDRAWAL_REQUESTED"].includes(
          result.data.moderationStatus,
        );
        if (earlier && !closed) {
          loadedEarlier.current = true;
          setPrependRevision((value) => value + 1);
        }
        setView((previous) => ({
          ...result.data,
          ...(closed
            ? {
                description: "",
                contact: undefined,
                title:
                  result.data.moderationStatus === "WITHDRAWN"
                    ? "已撤回的反馈"
                    : "撤回处理中的反馈",
              }
            : {}),
          messages: closed
            ? []
            : previous
              ? mergeMessages(previous.messages, result.data.messages)
              : result.data.messages,
        }));
        nextCursor.current = closed
          ? null
          : !earlier && loadedEarlier.current
            ? nextCursor.current
            : result.meta.nextCursor;
        setCursor(nextCursor.current);
        if (closed) {
          setDraft("");
          setIntent(undefined);
          setSent(false);
          if (redactedStatus.current !== result.data.moderationStatus) {
            redactedStatus.current = result.data.moderationStatus;
            await onRedacted(result.data.moderationStatus);
          }
        }
      } catch (problem) {
        if (
          mounted.current &&
          generation === epoch.current &&
          !active.signal.aborted
        )
          failure(problem);
      } finally {
        if (mounted.current && controller.current === active) {
          setLoading(false);
          if (earlier) {
            paging.current = false;
            onBusy(false);
          }
        }
      }
    },
    [base, failure, onBusy, admin, accountId, onRedacted],
  );

  // 会话版本来自可见页面的列表同步；轮询不碰用户草稿或焦点。
  useEffect(() => {
    let cancelled = false;
    // 把网络同步排到提交之后，也避免 StrictMode 预演启动无用的读取。
    void Promise.resolve().then(() => {
      if (!cancelled) return load();
    });
    return () => {
      cancelled = true;
    };
  }, [load, version]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
      onBusy(false);
    };
  }, [onBusy]);
  useEffect(() => {
    if (focusPending.current && !sending && !intent) {
      focusPending.current = false;
      textarea.current?.focus();
    }
  }, [sending, intent]);

  async function send(resolve = false, retry?: Intent) {
    if (lock.current || paging.current || !view?.canReply) return;
    const next = retry ?? {
      body: draft.trim(),
      key: crypto.randomUUID(),
      resolve,
    };
    if (!next.body) return;
    lock.current = true;
    controller.current?.abort();
    const generation = ++epoch.current;
    setLoading(false);
    onBusy(true);
    setSending(true);
    setIntent(next);
    setError(undefined);
    setSent(false);
    try {
      const receipt = await api<FeedbackMessageReceipt>(
        `${base}/messages`,
        "POST",
        admin
          ? { body: next.body, resolve: next.resolve }
          : { body: next.body },
        false,
        {
          idempotencyKey: next.key,
          expectedAccountId: admin ? undefined : accountId,
        },
      );
      if (!mounted.current || generation !== epoch.current) return;
      setView(
        (previous) =>
          previous && {
            ...previous,
            status: receipt.feedbackStatus,
            messages: mergeMessages(previous.messages, [receipt.message]),
          },
      );
      setDraft("");
      setIntent(undefined);
      setSent(true);
      focusPending.current = true;
      console.debug("[反馈聊天] 消息已确认发送");
    } catch (problem) {
      if (mounted.current && generation === epoch.current) {
        failure(problem);
        console.warn("[反馈聊天] 发送结果未确认，保留原意图");
      }
    } finally {
      lock.current = false;
      if (mounted.current) {
        setSending(false);
        onBusy(false);
        onUpdated();
      }
    }
  }
  async function withdraw() {
    if (
      admin ||
      lock.current ||
      paging.current ||
      !view ||
      ["WITHDRAWN", "WITHDRAWAL_REQUESTED"].includes(view.moderationStatus)
    )
      return;
    lock.current = true;
    controller.current?.abort();
    const generation = ++epoch.current;
    setLoading(false);
    setWithdrawing(true);
    setError(undefined);
    onBusy(true);
    try {
      const result = await api<FeedbackManagement>(
        `${base}/withdrawal`,
        "POST",
        {},
        false,
        { expectedAccountId: accountId },
      );
      if (!mounted.current || generation !== epoch.current) return;
      setView(
        (previous) =>
          previous && {
            ...previous,
            title:
              result.moderationStatus === "WITHDRAWN"
                ? "已撤回的反馈"
                : "撤回处理中的反馈",
            description: "",
            messages: [],
            canReply: false,
            unreadCount: 0,
            moderationStatus: result.moderationStatus,
          },
      );
      setDraft("");
      setIntent(undefined);
      setSent(false);
      setCursor(null);
      nextCursor.current = null;
      await onRedacted(result.moderationStatus);
      console.debug("[反馈聊天] 撤回结果已确认，私有对话已清理");
    } catch (problem) {
      if (mounted.current && generation === epoch.current) failure(problem);
    } finally {
      lock.current = false;
      if (mounted.current) {
        setWithdrawing(false);
        onBusy(false);
        onUpdated();
      }
    }
  }
  function rewrite() {
    setIntent(undefined);
    setError(undefined);
    focusPending.current = true;
  }
  function changeDraft(value: string) {
    setDraft(value);
    setSent(false);
  }
  return {
    view,
    cursor,
    loading,
    sending,
    withdrawing,
    error,
    draft,
    intent,
    sent,
    textarea,
    prependRevision,
    load,
    send,
    withdraw,
    rewrite,
    changeDraft,
  };
}
