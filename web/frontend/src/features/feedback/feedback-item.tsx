import { Button, Notice } from "@/components/ui";
import type { Feedback, FeedbackModerationInput } from "@/lib/types";
import { FeedbackModeration } from "./feedback-moderation";
import styles from "./feedback.module.css";

export { feedbackStatuses } from "./feedback-statuses";
import { feedbackStatuses } from "./feedback-statuses";
import { FeedbackConversationPanel } from "./feedback-conversation";
import type { ComponentProps } from "react";

const categories = {
  BUG: "使用问题",
  SUGGESTION: "功能建议",
  OTHER: "问题与建议",
} satisfies Record<Feedback["category"], string>;

const progressActions = ["NEW", "IN_PROGRESS", "RESOLVED"] as const;

export function FeedbackItem({
  item,
  busy = false,
  saving = false,
  error,
  onChange,
  onModerate,
  conversation,
}: {
  item: Feedback;
  busy?: boolean;
  saving?: boolean;
  error?: unknown;
  onChange?: (status: Feedback["status"]) => void;
  onModerate?: (decision: FeedbackModerationInput["decision"]) => void;
  conversation?: Omit<
    ComponentProps<typeof FeedbackConversationPanel>,
    "id" | "busy"
  >;
}) {
  const diagnostics = item.diagnostics;
  const needsCleanup = item.moderationStatus === "WITHDRAWAL_REQUESTED";
  // 官网标题取自正文首行，相同内容只显示一次，长正文仍完整可读。
  const hasDescription = item.description.trim() !== item.title.trim();
  const actionLabels = {
    NEW: item.status === "RESOLVED" ? "重新打开" : "移回待处理",
    IN_PROGRESS: item.status === "RESOLVED" ? "继续处理" : "开始处理",
    RESOLVED: "标记已解决",
  } satisfies Record<Feedback["status"], string>;
  return (
    <article className={styles.item} aria-label={item.title || "已撤回的反馈"}>
      <div className={styles.meta}>
        <span>{categories[item.category]}</span>
        <span className={styles.status}>
          {item.moderationStatus === "SPAM"
            ? "垃圾邮件"
            : feedbackStatuses[item.status]}
        </span>
        <time dateTime={item.createdAt}>
          {new Date(item.createdAt).toLocaleString("zh-CN")}
        </time>
      </div>
      <h3>{item.title || "已撤回的反馈"}</h3>
      {hasDescription && (
        <p className={styles.description}>{item.description}</p>
      )}
      {item.contact && (
        <dl className={styles.info}>
          <dt>联系方式</dt>
          <dd>{item.contact}</dd>
        </dl>
      )}
      {/* 垃圾邮件复用正文卡片；未提供事件时不展示状态或回复入口。 */}
      {onChange && (
        <div className={styles.actions} aria-label="修改处理状态">
          {progressActions
            .filter((status) => status !== item.status)
            .map((status) => (
              <Button
                key={status}
                className={status === "RESOLVED" ? "" : "secondary"}
                disabled={busy}
                onClick={() => onChange(status)}
              >
                {actionLabels[status]}
              </Button>
            ))}
        </div>
      )}
      {item.moderationStatus === "WITHDRAWN" ? (
        <Notice>这条反馈已撤回，原文与私有对话已清理。</Notice>
      ) : conversation ? (
        <FeedbackConversationPanel
          key={`${item.id}:${item.moderationStatus}`}
          id={item.id}
          busy={busy}
          {...conversation}
        />
      ) : null}
      {saving && <Notice>正在保存处理操作…</Notice>}
      {error !== undefined && <Notice error={error} />}
      {(onModerate || diagnostics) && (
        <details className={styles.extra} open={needsCleanup}>
          <summary>
            {needsCleanup ? "撤回请求：待清理公开内容" : "公开与其他操作"}
          </summary>
          {onModerate && (
            <FeedbackModeration
              item={item}
              busy={busy}
              onModerate={onModerate}
            />
          )}
          {diagnostics && (
            <div className={styles.technical}>
              <p className={styles.label}>版本与系统</p>
              <dl className={styles.diagnostics}>
                {(
                  [
                    ["软件版本", diagnostics.appVersion],
                    ["操作系统", diagnostics.system],
                    ["系统架构", diagnostics.architecture],
                    ["Python 版本", diagnostics.pythonVersion],
                    ["Qt 版本", diagnostics.qtVersion],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value || "未提供"}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </details>
      )}
    </article>
  );
}
