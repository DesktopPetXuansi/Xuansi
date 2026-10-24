"use client";
import { api, ApiError } from "@/lib/api";
import type {
  FeedbackConversation,
  FeedbackConversationResponse,
  FeedbackMessageReceipt,
} from "@/lib/types";
import { useEffect, useRef, useState } from "react";

type Intent = { key: string; body: string; resolve: boolean };
export type ConversationProps = {
  id: string;
  managementToken?: string;
  busy: boolean;
  begin: () => boolean;
  end: () => void;
  onDenied: (error: ApiError) => void;
  onSent: (receipt: FeedbackMessageReceipt) => void;
  onWithdrawn?: () => void;
};

// 私有正文只存组件内存，读取由操作触发；卸载时取消外部请求。
export function useFeedbackConversation({
  id,
  managementToken,
  busy,
  begin,
  end,
  onDenied,
  onSent,
  onWithdrawn,
}: ConversationProps) {
  const admin = managementToken === undefined;
  const [view, setView] = useState<FeedbackConversation>();
  const [opened, setOpened] = useState(false);
  const [cursor, setCursor] = useState<string | null>();
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [draft, setDraft] = useState("");
  const [intent, setIntent] = useState<Intent>();
  const [sent, setSent] = useState(false);
  const [denied, setDenied] = useState(false);
  const controller = useRef<AbortController | undefined>(undefined);
  const sendLock = useRef(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const focusAfterEdit = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);
  // 焦点同步必须等输入框实际解除禁用；动画帧可能早于生产构建的 DOM 提交。
  // sent 也作为提交标记，覆盖开始与结束状态恰好被合并的快速响应。
  useEffect(() => {
    if (!focusAfterEdit.current || busy || loading || intent) return;
    focusAfterEdit.current = false;
    // 筛选移除卡片时 ref 为空，保留父级列表的焦点恢复。
    textarea.current?.focus();
  }, [busy, loading, intent, sent]);

  async function load(earlier = false) {
    if (busy || loading || sendLock.current) return;
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;
    setOpened(true);
    setLoading(true);
    setError(undefined);
    try {
      const params = new URLSearchParams({ limit: "20" });
      if (earlier && cursor) params.set("cursor", cursor);
      const result = await api<FeedbackConversationResponse>(
        admin
          ? `/admin/feedback/${id}/messages?${params}`
          : `/feedback/${id}/messages/query`,
        admin ? "GET" : "POST",
        admin
          ? undefined
          : {
              managementToken,
              limit: 20,
              ...(earlier && cursor ? { cursor } : {}),
            },
        true,
        { signal: active.signal },
      );
      active.signal.throwIfAborted();
      const withdrawn = ["WITHDRAWN", "WITHDRAWAL_REQUESTED"].includes(
        result.data.moderationStatus,
      );
      // 撤回优先于分页：服务器清理后绝不把此前已读私信重新合并回来。
      if (withdrawn) {
        setDraft("");
        setIntent(undefined);
        setSent(false);
      }
      setView((previous) => ({
        ...result.data,
        messages: withdrawn
          ? []
          : earlier && previous
            ? [
                ...new Map(
                  [...result.data.messages, ...previous.messages].map(
                    (message) => [message.id, message],
                  ),
                ).values(),
              ]
            : result.data.messages,
      }));
      setCursor(withdrawn ? null : result.meta.nextCursor);
      if (result.data.moderationStatus === "WITHDRAWN") onWithdrawn?.();
      setDenied(false);
      console.debug("[私有对话] 对话已读取");
    } catch (failure) {
      // 取消不能恢复被权限错误清除的对话，也不能清除父级鉴权护栏。
      if (
        active.signal.aborted &&
        !(failure instanceof ApiError && [401, 403].includes(failure.status))
      )
        return;
      setError(failure);
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) {
        setView(undefined);
        setDenied(true);
        setDraft("");
        setIntent(undefined);
        onDenied(failure);
      }
      console.warn("[私有对话] 读取失败，可重新尝试");
    } finally {
      if (controller.current === active) setLoading(false);
    }
  }

  async function send(resolve = false, retry?: Intent) {
    const next = retry ?? {
      key: crypto.randomUUID(),
      body: draft.trim(),
      resolve,
    };
    if (
      !view?.canReply ||
      denied ||
      loading ||
      sendLock.current ||
      !next.body ||
      !begin()
    )
      return;
    sendLock.current = true;
    setSending(true);
    setSent(false);
    setError(undefined);
    setIntent(next);
    try {
      const receipt = await api<FeedbackMessageReceipt>(
        admin ? `/admin/feedback/${id}/messages` : `/feedback/${id}/messages`,
        "POST",
        admin
          ? { body: next.body, resolve: next.resolve }
          : { managementToken, body: next.body },
        false,
        { idempotencyKey: next.key },
      );
      setView(
        (previous) =>
          previous && {
            ...previous,
            status: receipt.feedbackStatus,
            messages: [
              ...new Map(
                [...previous.messages, receipt.message].map((message) => [
                  message.id,
                  message,
                ]),
              ).values(),
            ],
          },
      );
      setDraft("");
      setIntent(undefined);
      setSent(true);
      focusAfterEdit.current = true;
      onSent(receipt);
      console.debug("[私有对话] 消息已发送");
    } catch (failure) {
      setError(failure);
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) {
        setView(undefined);
        setDenied(true);
        setDraft("");
        setIntent(undefined);
        onDenied(failure);
      }
      console.warn("[私有对话] 发送未确认，保留原发送意图");
    } finally {
      sendLock.current = false;
      setSending(false);
      end();
    }
  }

  function changeDraft(value: string) {
    setDraft(value);
    setSent(false);
  }
  function rewrite() {
    setIntent(undefined);
    setError(undefined);
    focusAfterEdit.current = true;
  }
  return {
    admin,
    view,
    opened,
    cursor,
    loading,
    sending,
    error,
    draft,
    intent,
    sent,
    denied,
    textarea,
    load,
    send,
    rewrite,
    changeDraft,
  };
}
