"use client";
import { api, ApiError } from "@/lib/api";
import type { FeedbackInput, FeedbackReceipt, User } from "@/lib/types";
import { useEffect, useRef, useState, type FormEvent } from "react";

type Attempt = { key: string; accountId: string | null; body: FeedbackInput };

// 发送意图只存在当前身份内存中；离开页面取消请求，不写访客历史。
export function usePublicFeedback({
  user,
  identityBlocked,
  retryIdentity,
}: {
  user?: User | null;
  identityBlocked: boolean;
  retryIdentity: () => void;
}) {
  const [description, setDescription] = useState("");
  const [contact, setContact] = useState("");
  const [publicConsent, setPublicConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [attempt, setAttempt] = useState<Attempt>();
  const [receipt, setReceipt] = useState<FeedbackReceipt>();
  const lock = useRef(false);
  const focusNextDraft = useRef(false);
  const request = useRef<AbortController | undefined>(undefined);
  const accountId = user?.id ?? null;
  useEffect(() => () => request.current?.abort(), []);

  function startAgain() {
    focusNextDraft.current = true;
    setReceipt(undefined);
    setError(undefined);
    console.debug("[公众反馈] 开始新的反馈草稿");
  }
  // 回调 ref 仅在用户主动再写一条时恢复焦点，引用在构造它的 hook 内维护。
  function focusNewDraft(element: HTMLTextAreaElement | null) {
    if (element && focusNextDraft.current) {
      focusNextDraft.current = false;
      element.focus();
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lock.current || identityBlocked) return;
    const text = description.trim();
    if (!text) {
      setError(new Error("请先写下问题或建议。"));
      return;
    }
    lock.current = true;
    setBusy(true);
    setError(undefined);
    const active = new AbortController();
    request.current = active;
    try {
      const current =
        attempt ??
        ({
          key: crypto.randomUUID(),
          accountId,
          body: {
            category: "OTHER",
            title: Array.from(text.split(/\r?\n/, 1)[0]).slice(0, 80).join(""),
            description: text,
            contact: contact.trim(),
            publicConsent: accountId !== null && publicConsent,
          },
        } satisfies Attempt);
      setAttempt(current);
      setReceipt(undefined);
      if (current.accountId !== accountId)
        throw new Error("账号已切换，请重新填写后提交。");
      // 新访客只收件：不生成管理凭据，不持久保存草稿、正文或历史。
      const result = await api<FeedbackReceipt>(
        current.accountId ? "/me/feedback" : "/feedback",
        "POST",
        current.body,
        false,
        {
          idempotencyKey: current.key,
          signal: active.signal,
          expectedAccountId: current.accountId ?? undefined,
        },
      );
      active.signal.throwIfAborted();
      // 泛型不是运行时校验，只有属于本次请求的合法收据才能清空草稿。
      if (
        !result ||
        result.id !== current.key ||
        result.status !== "NEW" ||
        typeof result.createdAt !== "string" ||
        !Number.isFinite(Date.parse(result.createdAt))
      ) {
        throw new Error(
          "服务返回的反馈收据无法确认，草稿已保留，请重试这条反馈。",
        );
      }
      setReceipt(result);
      setAttempt(undefined);
      setDescription("");
      setContact("");
      setPublicConsent(false);
      console.debug("[公众反馈] 提交已确认，等待私有审核");
    } catch (failure) {
      if (active.signal.aborted) return;
      setError(failure);
      if (
        failure instanceof ApiError &&
        ([401, 403].includes(failure.status) ||
          failure.code === "ACCOUNT_CHANGED")
      )
        retryIdentity();
      // 明确的客户端拒绝允许修改；超时、网络或服务端错误仍复用原请求。
      if (
        failure instanceof ApiError &&
        failure.status >= 400 &&
        failure.status < 500 &&
        failure.status !== 408
      )
        setAttempt(undefined);
      console.warn("[公众反馈] 提交未确认，保留草稿与原请求");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return {
    description,
    setDescription,
    contact,
    setContact,
    publicConsent,
    setPublicConsent,
    busy,
    error,
    attempt,
    receipt,
    focusNewDraft,
    accountId,
    startAgain,
    submit,
  };
}
