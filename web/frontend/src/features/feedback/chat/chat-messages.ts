import type { FeedbackMessage } from "@/lib/types";

// 幂等重放可能返回早于当前末尾的消息，合并后仍按服务器的时间/id顺序展示。
export function mergeMessages(...pages: FeedbackMessage[][]) {
  return [
    ...new Map(pages.flat().map((message) => [message.id, message])).values(),
  ].sort((left, right) => {
    const time = Date.parse(left.createdAt) - Date.parse(right.createdAt);
    if (time) return time;
    const fraction = (value: string) =>
      (value.match(/\.(\d+)/)?.[1] ?? "").padEnd(9, "0");
    return (
      fraction(left.createdAt).localeCompare(fraction(right.createdAt)) ||
      left.id.localeCompare(right.id)
    );
  });
}
