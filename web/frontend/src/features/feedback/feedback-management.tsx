"use client";

import { Button, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
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

  async function perform(withdraw = false) {
    if (!credentials?.id || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    // 管理链接在用户操作时保存，避免渲染过程写浏览器存储。
    const persisted = saveCredentials(credentials);
    setStorage((previous) => ({ ...previous, warning: !persisted }));
    try {
      const result = await api<FeedbackManagement>(
        `/feedback/${credentials.id}/${withdraw ? "withdrawal" : "management"}`,
        "POST",
        { managementToken: credentials.managementToken },
      );
      setView(result);
      console.debug(
        withdraw ? "[公众反馈] 撤回结果已确认" : "[公众反馈] 管理状态已更新",
      );
    } catch (failure) {
      setError(failure);
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
          <p>已保存这条反馈的管理权限。可查看最新状态或申请撤回。</p>
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
            <span>专属管理链接（请勿分享，持有者可撤回反馈）</span>
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
