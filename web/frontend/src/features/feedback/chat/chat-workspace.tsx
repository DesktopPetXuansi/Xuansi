"use client";
import { useMe } from "@/components/navigation";
import { Button, Heading, Notice } from "@/components/ui";
import type { FeedbackManagement } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { ThreadItem } from "./chat-list-item";
import { ChatThread } from "./chat-thread";
import { useChatList } from "./use-chat-list";
import styles from "./chat.module.css";
import { redactChatCaches } from "./chat-cache";

export function FeedbackChat({ admin = false }: { admin?: boolean }) {
  const me = useMe();
  if (!me.data || (admin && me.data.role !== "ADMIN")) return null;
  // 身份发生变化即卸载全部正文、草稿和异步控制器，不复用前一账号的会话。
  return (
    <ChatWorkspace
      key={`${me.data.id}:${admin}`}
      identity={me.data.id}
      admin={admin}
    />
  );
}

function ChatWorkspace({
  identity,
  admin,
}: {
  identity: string;
  admin: boolean;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("id") ?? "";
  // URL不是权限凭据，也不能直接拼入API路径；只接收标准小写反馈编号。
  const selected =
    /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(requested) &&
    requested !== "00000000-0000-0000-0000-000000000000"
      ? requested
      : "";
  const base = admin ? "/admin/feedback/chat" : "/dashboard/feedback";
  const cache = useQueryClient();
  const [denied, setDenied] = useState(false);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const onDenied = useCallback(() => {
    setDenied(true);
    // 移除查询会同时取消读取；所有聊天缓存按命名空间清除，不保留私有旧快照。
    cache.removeQueries({ queryKey: ["feedback-chat"] });
    cache.removeQueries({ queryKey: ["admin-feedback"] });
    void cache.invalidateQueries({ queryKey: ["me"] });
    console.warn("[反馈聊天] 权限失效，已清除私有会话");
  }, [cache]);
  const onMissing = useCallback(() => {
    setMissing(true);
    router.replace(base, { scroll: false });
  }, [router, base]);
  if (denied)
    return (
      <Notice>
        会话权限已失效，请重新登录后查看。<Link href="/login">前往登录</Link>
      </Notice>
    );
  return (
    <ChatContent
      identity={identity}
      admin={admin}
      selected={selected}
      base={base}
      busy={busy}
      onBusy={setBusy}
      onDenied={onDenied}
      onMissing={onMissing}
      missing={missing || (!!requested && !selected)}
      onSelect={(id) => {
        setMissing(false);
        router.replace(id ? `${base}?id=${encodeURIComponent(id)}` : base, {
          scroll: false,
        });
      }}
    />
  );
}

function ChatContent({
  identity,
  admin,
  selected,
  base,
  busy,
  onBusy,
  onDenied,
  onMissing,
  missing,
  onSelect,
}: {
  identity: string;
  admin: boolean;
  selected: string;
  base: string;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  onDenied: () => void;
  onMissing: () => void;
  missing: boolean;
  onSelect: (id: string) => void;
}) {
  const query = useChatList(identity, admin, busy, onDenied);
  const cache = useQueryClient();
  const { refetch } = query;
  const onUpdated = useCallback(() => {
    void refetch();
  }, [refetch]);
  const onRedacted = useCallback(
    async (moderationStatus: FeedbackManagement["moderationStatus"]) => {
      await redactChatCaches(cache, selected, moderationStatus);
    },
    [cache, selected],
  );
  const thread = query.threads.find((item) => item.id === selected);
  const version = thread
    ? `${thread.updatedAt}:${thread.lastMessage?.id ?? ""}:${thread.status}:${thread.moderationStatus}`
    : "initial";
  return (
    <>
      <Heading title={admin ? "反馈对话" : "我的反馈"}>
        {admin
          ? "与反馈者直接沟通，问题与回复保留在同一会话。"
          : "这里保留你与玄司开发者的反馈对话。"}
      </Heading>
      <div className={styles.pageLinks}>
        {admin ? (
          <Link href="/admin/feedback">收件与审核 ↗</Link>
        ) : (
          <Link href="/#feedback">提交新的反馈 ↗</Link>
        )}
        <span>仅在页面可见时自动同步</span>
      </div>
      {missing && (
        <Notice>这条反馈不存在或已无法查看，请从列表选择其他会话。</Notice>
      )}
      <div className={styles.workspace} data-detail={!!selected}>
        <aside className={styles.listPane} aria-label="会话列表">
          <header className={styles.listHeader}>
            <h2>{admin ? "全部反馈" : "你的会话"}</h2>
            <Button
              className="secondary"
              disabled={busy || query.isFetching}
              onClick={onUpdated}
            >
              {selected ? "刷新列表" : "刷新会话"}
            </Button>
          </header>
          {query.isPending && <Notice>正在读取会话列表…</Notice>}
          {query.error && (
            <>
              <Notice error={query.error} />
              <Button
                className="secondary"
                disabled={busy || query.isFetching}
                onClick={onUpdated}
              >
                重试读取列表
              </Button>
            </>
          )}
          {!query.isPending && !query.error && !query.threads.length && (
            <p className={styles.empty}>
              {admin
                ? "暂时没有反馈。收到新问题后，会出现在这里。"
                : "还没有反馈会话。提交登录反馈后，即可在这里与开发者沟通。"}
            </p>
          )}
          <ul className={styles.threadList}>
            {query.threads.map((item) => (
              <ThreadItem
                key={item.id}
                thread={item}
                admin={admin}
                selected={item.id === selected}
                onSelect={onSelect}
              />
            ))}
          </ul>
          {query.hasNextPage && (
            <Button
              className="secondary"
              disabled={busy || query.isFetching}
              onClick={() => void query.fetchNextPage()}
            >
              加载更多会话
            </Button>
          )}
        </aside>
        {selected ? (
          <ChatThread
            key={`${identity}:${selected}`}
            id={selected}
            admin={admin}
            accountId={identity}
            thread={thread}
            version={version}
            onDenied={onDenied}
            onMissing={onMissing}
            onUpdated={onUpdated}
            onBusy={onBusy}
            onRedacted={onRedacted}
            onBack={() => onSelect("")}
          />
        ) : (
          <div className={styles.welcome}>
            <span className={styles.welcomeMark} aria-hidden="true">
              司
            </span>
            <h2>{admin ? "一条反馈，一段对话。" : "把问题聊清楚。"}</h2>
            <p>选择一条反馈，查看问题和后续消息。</p>
            <p className={styles.muted}>对话不会公开到 GitHub。</p>
            {!admin && <Link href="/#feedback">提交反馈</Link>}
          </div>
        )}
      </div>
      {/* 保留稳定路由，浏览器前进/后退和外部反馈链接都可直接打开同一会话。 */}
      <Link className={styles.allLink} href={base}>
        查看全部{admin ? "反馈" : "我的反馈"}
      </Link>
    </>
  );
}
