import { Button, Notice } from "@/components/ui";
import type { Feedback } from "@/lib/types";
import styles from "./feedback.module.css";

export const feedbackStatuses = {
  NEW: "待处理",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
} satisfies Record<Feedback["status"], string>;

const categories = {
  BUG: "使用问题",
  SUGGESTION: "功能建议",
  OTHER: "其他",
} satisfies Record<Feedback["category"], string>;

export function FeedbackItem({
  item,
  busy,
  saving,
  error,
  onChange,
}: {
  item: Feedback;
  busy: boolean;
  saving: boolean;
  error?: unknown;
  onChange: (status: Feedback["status"]) => void;
}) {
  const diagnostics = item.diagnostics;
  return (
    <article className={styles.item} aria-label={item.title}>
      <div className={styles.meta}>
        <span>{categories[item.category]}</span>
        <span className={styles.status}>{feedbackStatuses[item.status]}</span>
        <time dateTime={item.createdAt}>
          {new Date(item.createdAt).toLocaleString("zh-CN")}
        </time>
      </div>
      <h2>{item.title}</h2>
      <details>
        <summary>查看反馈与处理</summary>
        <p className={styles.description}>{item.description}</p>
        <dl className={styles.info}>
          <dt>联系方式</dt>
          <dd>{item.contact || "未填写"}</dd>
          <dt>版本与系统</dt>
          <dd>
            {diagnostics ? (
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
            ) : (
              "未附带"
            )}
          </dd>
        </dl>
        <p className={styles.label}>处理状态</p>
        <div className={styles.actions} aria-label="修改处理状态">
          {Object.entries(feedbackStatuses).map(([status, label]) => (
            <Button
              key={status}
              className="secondary"
              disabled={busy || status === item.status}
              onClick={() => {
                // 状态值来自同一枚举，避免接纳外部输入作为处理操作。
                if (
                  status === "NEW" ||
                  status === "IN_PROGRESS" ||
                  status === "RESOLVED"
                )
                  onChange(status);
              }}
            >
              标记为{label}
            </Button>
          ))}
        </div>
        {saving && <Notice>正在保存处理状态…</Notice>}
        {error !== undefined && <Notice error={error} />}
      </details>
    </article>
  );
}
