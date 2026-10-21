import { Notice } from "@/components/ui";
import type { FeedbackManagement } from "@/lib/types";

// 公开投递后的申请不能被描述为已经删除，避免给用户错误承诺。
export function ManagementStatus({ view }: { view: FeedbackManagement }) {
  const messages = {
    WITHDRAWN: "已撤回，站内正文及联系方式已清理。",
    WITHDRAWAL_REQUESTED:
      "撤回申请已收到。内容可能已经公开，管理员需要在 GitHub 清理后确认，暂时不能保证公开内容已删除。",
    APPROVED: "反馈已审核通过；如已进入公开投递，撤回将由管理员人工处理。",
    SPAM: "这条反馈已停止处理。",
    PENDING: "反馈正在私有待审核，尚未公开。",
  } satisfies Record<FeedbackManagement["moderationStatus"], string>;
  return <Notice>{messages[view.moderationStatus]}</Notice>;
}
