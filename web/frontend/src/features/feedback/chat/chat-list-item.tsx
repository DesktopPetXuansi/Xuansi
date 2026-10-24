import type { FeedbackThread } from "@/lib/types";
import { feedbackStatuses } from "../feedback-statuses";
import styles from "./chat.module.css";

// 会话摘要只展示授权列表中的昵称与末条消息。
export function ThreadItem({
  thread,
  admin,
  selected,
  onSelect,
}: {
  thread: FeedbackThread;
  admin: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const name = admin ? thread.participant.displayName : "玄司开发者";
  return (
    <li>
      <button
        className={styles.threadButton}
        aria-current={selected ? "true" : undefined}
        onClick={() => onSelect(thread.id)}
      >
        <span className={styles.threadIdentity}>
          <strong>{name}</strong>
          {thread.unreadCount > 0 && (
            <span
              className={styles.unread}
              aria-label={`${thread.unreadCount} 条未读消息`}
            >
              {thread.unreadCount > 99 ? "99+" : thread.unreadCount}
            </span>
          )}
        </span>
        <span className={styles.threadTitle}>{thread.title}</span>
        <span className={styles.preview}>
          {thread.lastMessage?.body || thread.preview || "内容已撤回"}
        </span>
        <span className={styles.threadFoot}>
          <span>
            {feedbackStatuses[thread.status]}
            {thread.participant.kind === "GUEST" && !thread.canReply
              ? " · 访客单次反馈"
              : ""}
          </span>
          <time dateTime={thread.updatedAt}>
            {new Date(thread.updatedAt).toLocaleDateString("zh-CN", {
              month: "numeric",
              day: "numeric",
            })}
          </time>
        </span>
      </button>
    </li>
  );
}
