"use client";

import { Button, Notice } from "@/components/ui";
import { api, ApiError, safeUrl } from "@/lib/api";
import type { FeedbackManagement } from "@/lib/types";
import { useRef, useState, useSyncExternalStore } from "react";
import {
  managementLink,
  readSavedCredentials,
  restoreCredentials,
  saveCredentials,
  type FeedbackCredentials,
} from "./management-storage";
import styles from "./public-feedback.module.css";
import { ManagementStatus } from "./management-status";
import { FeedbackConversationPanel } from "./feedback-conversation";
import { FeedbackClaim } from "./feedback-claim";

const subscribe = (listener: () => void) => {
  window.addEventListener("hashchange", listener);
  window.addEventListener("popstate", listener);
  return () => {
    window.removeEventListener("hashchange", listener);
    window.removeEventListener("popstate", listener);
  };
};

export function FeedbackManagementPanel(props: {
  credentials?: FeedbackCredentials;
}) {
  // 以 React 的外部快照区分 SSR 与浏览器，恢复凭据时不产生水合差异。
  const fragment = useSyncExternalStore(
    subscribe,
    () => window.location.hash,
    () => null,
  );
  return fragment !== null ? (
    <BrowserManagementPanel key={fragment} {...props} />
  ) : (
    <Notice>正在读取本浏览器的反馈管理凭据…</Notice>
  );
}

function BrowserManagementPanel({
  credentials: provided,
}: {
  credentials?: FeedbackCredentials;
}) {
  const [credentials, setCredentials] = useState(
    () => provided ?? restoreCredentials(),
  );
  const [view, setView] = useState<FeedbackManagement>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState(() =>
    credentials ? managementLink(credentials) : "",
  );
  const [copied, setCopied] = useState(false);
  const [storage, setStorage] = useState(() => {
    try {
      return { saved: readSavedCredentials(), warning: false };
    } catch {
      return { saved: [] as FeedbackCredentials[], warning: true };
    }
  });
  const { saved, warning: storageWarning } = storage;
  const lock = useRef(false);
  const accessEpoch = useRef(0);
  const [conversationVersion, setConversationVersion] = useState(0);
  const [denied, setDenied] = useState(false);
  function beginConversation() {
    if (lock.current) return false;
    lock.current = true;
    setBusy(true);
    return true;
  }
  function endConversation() {
    lock.current = false;
    setBusy(false);
  }
  function denyConversation(failure: ApiError) {
    accessEpoch.current += 1;
    setView(undefined);
    setDenied(true);
    setError(failure);
  }

  async function perform(withdraw = false) {
    if (!credentials?.id || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    const startedAccessEpoch = accessEpoch.current;
    // 管理链接在用户操作时保存，避免渲染过程写浏览器存储。
    const persisted = saveCredentials(credentials);
    setStorage((previous) => ({ ...previous, warning: !persisted }));
    try {
      const result = await api<FeedbackManagement>(
        `/feedback/${credentials.id}/${withdraw ? "withdrawal" : "management"}`,
        "POST",
        { managementToken: credentials.managementToken },
      );
      // 更早的成功读取不能解除后来出现的凭据失效护栏。
      if (accessEpoch.current !== startedAccessEpoch) return;
      setView(result);
      setDenied(false);
      if (withdraw) setConversationVersion((previous) => previous + 1);
      console.debug(
        withdraw ? "[公众反馈] 撤回结果已确认" : "[公众反馈] 管理状态已更新",
      );
    } catch (failure) {
      setError(failure);
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) {
        accessEpoch.current += 1;
        setView(undefined);
        setDenied(true);
        setConversationVersion((previous) => previous + 1);
      }
      console.warn("[公众反馈] 管理操作失败，可重新尝试");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  if (!credentials)
    return (
      <Notice>
        {window.location.hash
          ? "管理链接无效或不完整，请使用提交后保存的完整链接。为避免操作其他反馈，此页不会自动切换到本机保存的记录。"
          : "本浏览器没有保存反馈记录。请使用提交后保存的完整管理链接打开此页；清除浏览器数据且没有链接时，请联系管理员。"}
      </Notice>
    );
  return (
    <div className={styles.management}>
      {!provided && saved.length > 1 && (
        <label className="field">
          <span>本浏览器保存的反馈</span>
          <select
            disabled={busy}
            value={credentials.idempotencyKey}
            onChange={(event) => {
              const selected = saved.find(
                (item) => item.idempotencyKey === event.target.value,
              );
              if (selected) {
                setCredentials(selected);
                setLink(managementLink(selected));
                setView(undefined);
                setDenied(false);
                setError(undefined);
                console.debug("[公众反馈] 切换已保存反馈");
              }
            }}
          >
            {saved.map((item, index) => (
              <option key={item.idempotencyKey} value={item.idempotencyKey}>
                反馈 {index + 1}
                {item.id ? ` · ${item.id.slice(0, 8)}` : " · 提交未确认"}
              </option>
            ))}
          </select>
        </label>
      )}
      {credentials.id ? (
        <>
          <p>
            已保存这条反馈的管理权限。可查看开发者回复、补充说明或申请撤回。
          </p>
          <div className="actions">
            <Button
              className="secondary"
              disabled={busy}
              onClick={() => void perform()}
            >
              查看最新状态
            </Button>
            <Button
              className="secondary"
              disabled={
                busy ||
                view?.moderationStatus === "WITHDRAWN" ||
                view?.moderationStatus === "WITHDRAWAL_REQUESTED"
              }
              onClick={() => void perform(true)}
            >
              {view?.canWithdraw === false ? "申请撤回公开内容" : "撤回反馈"}
            </Button>
          </div>
        </>
      ) : (
        <Notice>
          这次提交尚未确认成功，请回到原页面重试并保留草稿。如已关闭原页面，请联系管理员核实提交结果。
        </Notice>
      )}
      {view && <ManagementStatus view={view} />}
      {credentials.id &&
        !denied &&
        view?.moderationStatus !== "WITHDRAWN" &&
        view?.moderationStatus !== "WITHDRAWAL_REQUESTED" && (
          <FeedbackClaim
            credentials={credentials}
            busy={busy}
            begin={beginConversation}
            end={endConversation}
            onClaimed={() => {
              accessEpoch.current += 1;
              setView(undefined);
              setDenied(true);
              setLink("");
              setConversationVersion((previous) => previous + 1);
            }}
          />
        )}
      {credentials.id &&
        !denied &&
        view?.moderationStatus !== "WITHDRAWN" &&
        view?.moderationStatus !== "WITHDRAWAL_REQUESTED" && (
          <FeedbackConversationPanel
            key={`${credentials.id}:${conversationVersion}`}
            id={credentials.id}
            managementToken={credentials.managementToken}
            busy={busy}
            begin={beginConversation}
            end={endConversation}
            onDenied={denyConversation}
            onSent={() => {
              console.debug("[公众反馈] 补充说明已发送");
            }}
          />
        )}
      {view?.githubIssueUrl && (
        <a href={safeUrl(view.githubIssueUrl)} target="_blank" rel="noreferrer">
          查看公开问题 ↗
        </a>
      )}
      {error !== undefined && <Notice error={error} />}
      {storageWarning && (
        <Notice>
          浏览器禁止保存管理凭据。离开前请复制下方完整管理链接，否则可能无法自行撤回。
        </Notice>
      )}
      {link && (
        <>
          <label className="field">
            <span>
              专属管理链接（请勿分享，持有者可查看对话、补充及撤回反馈）
            </span>
            <input
              readOnly
              value={link}
              onFocus={(event) => event.target.select()}
            />
          </label>
          <Button
            className="secondary"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(link);
                setCopied(true);
                console.debug("[公众反馈] 管理链接已复制");
              } catch {
                setError(new Error("未能复制，请选中上方完整链接手动复制。"));
              }
            }}
          >
            {copied ? "已复制管理链接" : "复制管理链接"}
          </Button>
        </>
      )}
    </div>
  );
}
