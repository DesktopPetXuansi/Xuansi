import { Button } from "@/components/ui";
import { safeUrl } from "@/lib/api";
import type { Feedback, FeedbackModerationInput } from "@/lib/types";
import { useState } from "react";
import styles from "./feedback.module.css";

const moderationStatuses = {
  PENDING: "待审核",
  APPROVED: "已审核",
  SPAM: "垃圾反馈",
  WITHDRAWN: "已撤回",
  WITHDRAWAL_REQUESTED: "待清理公开内容",
} satisfies Record<Feedback["moderationStatus"], string>;

// 审核独立于处理进度；公开内容必须由管理员先清理，再确认撤回。
export function FeedbackModeration({
  item,
  busy,
  onModerate,
}: {
  item: Feedback;
  busy: boolean;
  onModerate: (decision: FeedbackModerationInput["decision"]) => void;
}) {
  const [cleaned, setCleaned] = useState(false);
  return (
    <div>
      <p>
        审核状态：{moderationStatuses[item.moderationStatus]} ·{" "}
        {item.publicConsent ? "作者允许审核后公开" : "未授权公开，仅私有处理"}
      </p>
      {item.githubIssueUrl && (
        <p>
          <a
            href={safeUrl(item.githubIssueUrl)}
            target="_blank"
            rel="noreferrer"
          >
            查看 GitHub 公开内容 ↗
          </a>
        </p>
      )}
      <div className={styles.actions}>
        {item.moderationStatus === "PENDING" && (
          <>
            <Button
              className="secondary"
              disabled={busy || !item.publicConsent}
              onClick={() => onModerate("APPROVE")}
            >
              {item.publicConsent ? "审核通过并排队公开" : "未授权公开"}
            </Button>
            <Button
              className="secondary"
              disabled={busy}
              onClick={() => onModerate("SPAM")}
            >
              标记为垃圾反馈
            </Button>
          </>
        )}
        {/* 管理响应以公开链接表示已取得 Issue；重试复用审核动作，由服务端协调投递任务。 */}
        {item.moderationStatus === "APPROVED" &&
          item.publicConsent &&
          !item.githubIssueUrl && (
            <Button
              className="secondary"
              disabled={busy}
              onClick={() => onModerate("APPROVE")}
            >
              重试同步到 GitHub
            </Button>
          )}
        {item.moderationStatus === "WITHDRAWAL_REQUESTED" && (
          <div>
            <p>
              请先在 GitHub 删除这条反馈的公开 Issue
              及相关公开内容。下面的确认只会清理站内记录，不会代替 GitHub
              删除；已经被他人保存的内容无法保证清除。
            </p>
            <label className={styles.confirmation}>
              <input
                type="checkbox"
                checked={cleaned}
                disabled={busy}
                onChange={(event) => setCleaned(event.target.checked)}
              />{" "}
              我已检查投递结果并在 GitHub 完成公开内容清理
            </label>
            <div>
              <Button
                className="secondary"
                disabled={busy || !cleaned}
                onClick={() => onModerate("CONFIRM_WITHDRAWAL")}
              >
                确认清理并完成撤回
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
