"use client";
import { Button, Notice } from "@/components/ui";
import { feedbackStatuses } from "./feedback-statuses";
import {
  useFeedbackConversation,
  type ConversationProps,
} from "./use-feedback-conversation";
import styles from "./feedback-conversation.module.css";

export function FeedbackConversationPanel(props: ConversationProps) {
  const { busy } = props;
  const {
    admin,
    view,
    opened,
    cursor,
    loading,
    sending,
    error,
    draft,
    intent,
    sent,
    denied,
    textarea,
    load,
    send,
    rewrite,
    changeDraft,
  } = useFeedbackConversation(props);
  if (!opened)
    return (
      <Button className="secondary" disabled={busy} onClick={() => void load()}>
        {admin ? "回复用户" : "查看对话"}
      </Button>
    );
  return (
    <section
      className={styles.conversation}
      aria-label="私有对话"
      aria-busy={loading || sending}
    >
      <div className={styles.header}>
        <h4>私有对话</h4>
        <Button
          className="secondary"
          disabled={busy || loading}
          onClick={() => void load()}
        >
          刷新对话
        </Button>
      </div>
      <p className={styles.hint}>
        仅你与开发者可见，不会公开到 GitHub。
        {!admin && "补充说明会让反馈重新进入待处理。"}
      </p>
      {loading && <Notice>正在读取对话…</Notice>}
      {error !== undefined && <Notice error={error} />}
      {view && !denied && (
        <>
          <p>处理进度：{feedbackStatuses[view.status]}</p>
          <details>
            <summary>原始问题</summary>
            <p className={styles.body}>{view.description}</p>
          </details>
          {cursor && (
            <Button
              className="secondary"
              disabled={busy || loading}
              onClick={() => void load(true)}
            >
              加载更早消息
            </Button>
          )}
          {view.messages.length ? (
            <ol className={styles.messages}>
              {view.messages.map((message) => (
                <li
                  key={message.id}
                  className={
                    message.authorRole === "ADMIN" ? styles.developer : ""
                  }
                >
                  <div className={styles.meta}>
                    <strong>
                      {message.authorRole === "ADMIN"
                        ? "开发者"
                        : admin
                          ? "用户"
                          : "你"}
                    </strong>
                    <time dateTime={message.createdAt}>
                      {new Date(message.createdAt).toLocaleString("zh-CN")}
                    </time>
                  </div>
                  <p className={styles.body}>{message.body}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.hint}>暂无对话记录。</p>
          )}
          {view.canReply ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <label className="field">
                <span>{admin ? "回复内容" : "补充说明"}</span>
                <textarea
                  aria-label={admin ? "回复内容" : "补充说明"}
                  ref={textarea}
                  rows={4}
                  maxLength={4000}
                  required
                  value={draft}
                  disabled={busy || loading || intent !== undefined}
                  onChange={(event) => {
                    changeDraft(event.target.value);
                  }}
                />
              </label>
              {intent && !sending ? (
                <>
                  <Notice>
                    上次发送结果尚未确认。重试会使用相同正文和请求编号；若改写，将作为一条新消息。
                  </Notice>
                  <div className={styles.actions}>
                    <Button
                      type="button"
                      disabled={busy || loading}
                      onClick={() => void send(intent.resolve, intent)}
                    >
                      重试发送
                    </Button>
                    <Button
                      type="button"
                      className="secondary"
                      disabled={busy || loading}
                      onClick={rewrite}
                    >
                      改写为新消息
                    </Button>
                  </div>
                </>
              ) : (
                <div className={styles.actions}>
                  <Button
                    type="submit"
                    disabled={busy || loading || !draft.trim()}
                  >
                    {sending ? "正在发送…" : admin ? "发送回复" : "发送补充"}
                  </Button>
                  {admin && (
                    <Button
                      type="button"
                      className="secondary"
                      disabled={busy || loading || !draft.trim()}
                      onClick={() => void send(true)}
                    >
                      回复并标记已解决
                    </Button>
                  )}
                </div>
              )}
            </form>
          ) : (
            <Notice>
              这条反馈已关闭对话，或没有原始管理凭据，暂不能新增消息。
            </Notice>
          )}
        </>
      )}
      {sent && <Notice>{admin ? "回复已发送。" : "补充已发送。"}</Notice>}
    </section>
  );
}
