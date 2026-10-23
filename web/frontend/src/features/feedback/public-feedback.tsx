"use client";

import { Button, Field, Notice } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { FeedbackInput, FeedbackReceipt } from "@/lib/types";
import { useRef, useState, type FormEvent } from "react";
import { FeedbackConfirmation } from "./feedback-confirmation";
import { FeedbackManagementPanel } from "./feedback-management";
import {
  createCredentials,
  saveCredentials,
  type FeedbackCredentials,
} from "./management-storage";
import styles from "./public-feedback.module.css";

type Attempt = { credentials: FeedbackCredentials; body: FeedbackInput };

// 表单只在用户操作时请求；正文保留在内存，重试复用同一份输入与幂等编号。
export function PublicFeedback() {
  const [description, setDescription] = useState("");
  const [contact, setContact] = useState("");
  const [publicConsent, setPublicConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [attempt, setAttempt] = useState<Attempt>();
  const [receipt, setReceipt] = useState<FeedbackCredentials>();
  const [storageWarning, setStorageWarning] = useState(false);
  const lock = useRef(false);
  const focusNextDraft = useRef(false);

  function startAgain() {
    focusNextDraft.current = true;
    setReceipt(undefined);
    setStorageWarning(false);
    setError(undefined);
    console.debug("[公众反馈] 开始新的反馈草稿");
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lock.current) return;
    const text = description.trim();
    if (!text) {
      setError(new Error("请先写下问题或建议。"));
      return;
    }
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const current =
        attempt ??
        ({
          credentials: createCredentials(),
          body: {
            category: "OTHER",
            title: Array.from(text.split(/\r?\n/, 1)[0]).slice(0, 80).join(""),
            description: text,
            contact: contact.trim(),
            publicConsent,
          },
        } satisfies Attempt);
      setAttempt(current);
      setReceipt(undefined);
      // 网络发送之前保存凭据，即使响应丢失也不会丢弃撤回权限。
      setStorageWarning(!saveCredentials(current.credentials));
      const result = await api<FeedbackReceipt>(
        "/feedback",
        "POST",
        {
          ...current.body,
          managementToken: current.credentials.managementToken,
        },
        false,
        { idempotencyKey: current.credentials.idempotencyKey },
      );
      // 泛型不是运行时校验，只有属于本次请求的合法收据才能清空草稿。
      if (
        !result ||
        result.id !== current.credentials.idempotencyKey ||
        result.status !== "NEW" ||
        typeof result.createdAt !== "string" ||
        !Number.isFinite(Date.parse(result.createdAt))
      ) {
        throw new Error(
          "服务返回的反馈收据无法确认，草稿已保留，请重试这条反馈。",
        );
      }
      const saved = { ...current.credentials, id: result.id };
      setStorageWarning(!saveCredentials(saved));
      setReceipt(saved);
      setAttempt(undefined);
      setDescription("");
      setContact("");
      setPublicConsent(false);
      console.debug("[公众反馈] 提交已确认，等待私有审核");
    } catch (failure) {
      setError(failure);
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
  return (
    <section
      id="feedback"
      className={styles.section}
      aria-labelledby="feedback-title"
    >
      <div>
        <p className="eyebrow">一起把玄司做得更好</p>
        <h2 id="feedback-title">有问题或建议？</h2>
        <p>不用注册，写下遇到的问题或希望增加的功能即可。</p>
        <p>默认仅开发者可见。请勿填写密码、API 密钥等敏感内容。</p>
        <a className="quiet-link" href="/feedback/manage">
          查看我的反馈 →
        </a>
      </div>
      <div className={styles.form}>
        {receipt ? (
          <FeedbackConfirmation
            credentials={receipt}
            storageWarning={storageWarning}
            onStartAgain={startAgain}
          />
        ) : (
          <form
            className={styles.form}
            onSubmit={(event) => void submit(event)}
            aria-busy={busy}
          >
            <Field label="问题或建议">
              <textarea
                ref={(element) => {
                  // 仅在主动再写一条时移动焦点，首次打开首页不抢占输入焦点。
                  if (element && focusNextDraft.current) {
                    focusNextDraft.current = false;
                    element.focus();
                  }
                }}
                required
                maxLength={4000}
                rows={4}
                value={description}
                disabled={busy || attempt !== undefined}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="遇到了什么？可以写下操作步骤，或你期待的功能……"
              />
            </Field>
            <details className={styles.options}>
              <summary>联系方式与公开选项（选填）</summary>
              <div className={styles.optionFields}>
                <Field
                  label="联系方式（选填）"
                  hint="仅开发者可见，方便需要时联系你。"
                >
                  <input
                    maxLength={160}
                    value={contact}
                    disabled={busy || attempt !== undefined}
                    onChange={(event) => setContact(event.target.value)}
                    placeholder="邮箱、QQ 或其他联系方式"
                  />
                </Field>
                <label className={styles.consent}>
                  <input
                    type="checkbox"
                    checked={publicConsent}
                    disabled={busy || attempt !== undefined}
                    onChange={(event) => setPublicConsent(event.target.checked)}
                  />
                  <span>
                    我同意审核后将反馈正文公开到 GitHub，联系方式不公开。
                  </span>
                </label>
              </div>
            </details>
            {error !== undefined && <Notice error={error} />}
            {attempt && !busy && (
              <small>
                草稿已保留。为避免重复提交，重试会发送相同内容；确认收到后可继续提交其他反馈。
              </small>
            )}
            <div>
              <Button type="submit" disabled={busy}>
                {busy ? "正在提交…" : attempt ? "重试这条反馈" : "提交反馈"}
              </Button>
            </div>
          </form>
        )}
        {!receipt && attempt && !busy && storageWarning && (
          <Notice>
            浏览器未能保存这条反馈。请复制下方管理链接，以便日后查看或撤回。
          </Notice>
        )}
        {!receipt &&
          attempt &&
          !busy &&
          (storageWarning ? (
            <FeedbackManagementPanel credentials={attempt.credentials} />
          ) : (
            <details className={styles.options}>
              <summary>查看这次提交的状态</summary>
              <FeedbackManagementPanel credentials={attempt.credentials} />
            </details>
          ))}
      </div>
    </section>
  );
}
