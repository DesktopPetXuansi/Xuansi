import Link from "next/link";
import { CircleCheck } from "lucide-react";
import { Button, Notice } from "@/components/ui";
import { FeedbackManagementPanel } from "./feedback-management";
import type { FeedbackCredentials } from "./management-storage";
import styles from "./public-feedback.module.css";

// 成功确认由提交事件挂载，聚焦标题让键盘及读屏用户明确知道操作已完成。
function focusConfirmation(element: HTMLHeadingElement | null) {
  element?.focus();
}

export function FeedbackConfirmation({
  credentials,
  storageWarning,
  onStartAgain,
}: {
  credentials: FeedbackCredentials;
  storageWarning: boolean;
  onStartAgain: () => void;
}) {
  return (
    <>
      <div className={styles.confirmation} role="status">
        <CircleCheck aria-hidden="true" size={24} />
        <div>
          <h3 ref={focusConfirmation} tabIndex={-1}>
            反馈已收到
          </h3>
          <p>已提交给开发者，感谢你帮助玄司改进。</p>
          {!storageWarning && <small>可在本浏览器查看进度或撤回。</small>}
        </div>
      </div>
      <div className="actions">
        <Button type="button" className="secondary" onClick={onStartAgain}>
          再写一条
        </Button>
        <Link className="quiet-link" href="/feedback/manage">
          查看或撤回反馈 →
        </Link>
      </div>
      {/* 存储失败时保留完整管理链接，避免简化展示后丢失独立撤回权限。 */}
      {storageWarning && (
        <>
          <Notice>
            浏览器未能保存这条反馈。请复制下方管理链接，以便日后查看或撤回。
          </Notice>
          <FeedbackManagementPanel credentials={credentials} />
        </>
      )}
    </>
  );
}
