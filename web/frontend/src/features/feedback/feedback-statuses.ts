import type { Feedback } from "@/lib/types";
export const feedbackStatuses = {
  NEW: "待处理",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
} satisfies Record<Feedback["status"], string>;
