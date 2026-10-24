import Link from "next/link";
import { CircleCheck } from "lucide-react";
import { Button } from "@/components/ui";
import type { FeedbackReceipt } from "@/lib/types";
import styles from "./public-feedback.module.css";

// 成功确认由提交事件挂载，聚焦标题让键盘及读屏用户明确知道操作已完成。
function focusConfirmation(element: HTMLHeadingElement | null) {
  element?.focus();
}

export function FeedbackConfirmation({
  receipt,
  account,
  onStartAgain,
}: {
  receipt: FeedbackReceipt;
  account: boolean;
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
          <small>
            {account
              ? "已保存到你的账号，可在“我的反馈”继续沟通。"
              : "这次匿名提交不建立聊天，也不在本浏览器保存反馈历史。"}
          </small>
        </div>
      </div>
      <div className="actions">
        <Button type="button" className="secondary" onClick={onStartAgain}>
          再写一条
        </Button>
        {account && (
          <Link
            className="quiet-link"
            href={`/dashboard/feedback?id=${receipt.id}`}
          >
            打开反馈会话 →
          </Link>
        )}
      </div>
    </>
  );
}
