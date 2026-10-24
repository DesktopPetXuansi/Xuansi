"use client";
import { Button, Notice } from "@/components/ui";
import type { FeedbackThread } from "@/lib/types";
import { useState } from "react";
import { feedbackStatuses } from "../feedback-statuses";
import { ChatHistory } from "./chat-history";
import { useChatMessages, type ChatAccess } from "./use-chat-messages";
import styles from "./chat.module.css";

export function ChatThread(
  props: ChatAccess & { thread?: FeedbackThread; onBack: () => void },
) {
  const state = useChatMessages(props);
  const [confirmWithdrawal, setConfirmWithdrawal] = useState(false);
  const {
    view,
    loading,
    sending,
    withdrawing,
    intent,
    error,
    draft,
    sent,
    textarea,
    prependRevision,
    cursor,
    load,
    send,
    withdraw,
    rewrite,
    changeDraft,
  } = state;
  return (
    <section
      className={styles.thread}
      aria-label="反馈会话"
      aria-busy={loading || sending || withdrawing}
    >
      <header className={styles.threadHeader}>
        <div>
          <button
            aria-label="返回会话列表"
            className={`${styles.textButton} ${styles.back}`}
            onClick={props.onBack}
          >
            ← 返回会话列表
          </button>
          <p className={styles.eyebrow}>
            {props.admin
              ? view?.participant?.displayName ||
                props.thread?.participant.displayName ||
                "反馈者"
              : "玄司开发者"}
          </p>
          <h2>{view?.title || props.thread?.title || "反馈对话"}</h2>
        </div>
        <Button
          className="secondary"
          disabled={loading || sending || withdrawing}
          onClick={() => {
            props.onUpdated();
            void load();
          }}
        >
          刷新会话
        </Button>
      </header>
      {loading && <Notice>{view ? "正在同步消息…" : "正在读取会话…"}</Notice>}
      {error !== undefined && <Notice error={error} />}
      {view && (
        <>
          <div className={styles.context}>
            <span className={styles.status}>
              {feedbackStatuses[view.status]}
            </span>
            <span>仅你与{props.admin ? "反馈者" : "开发者"}可见</span>
            <span>会话 {view.id.slice(-8)}</span>
          </div>
          {props.admin && view.contact && (
            <p className={styles.contact}>
              反馈者留下的联系方式：{view.contact}
            </p>
          )}
          {cursor && (
            <Button
              className="secondary"
              disabled={loading || sending}
              onClick={() => void load(true)}
            >
              加载更早消息
            </Button>
          )}
          <ChatHistory
            view={view}
            admin={props.admin}
            busy={loading || sending || withdrawing}
            accountId={props.accountId}
            prependRevision={prependRevision}
            onUpdated={props.onUpdated}
            onDenied={props.onDenied}
            onMissing={props.onMissing}
          />
          {view.canReply ? (
            <form
              className={styles.composer}
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <label className="field">
                <span>消息内容</span>
                <textarea
                  ref={textarea}
                  aria-label="消息内容"
                  rows={3}
                  maxLength={4000}
                  required
                  value={draft}
                  disabled={sending || withdrawing || !!intent}
                  onChange={(event) => changeDraft(event.target.value)}
                  placeholder={
                    props.admin
                      ? "回复这位反馈者…"
                      : "补充情况，或继续与开发者沟通…"
                  }
                />
              </label>
              {intent && !sending ? (
                <>
                  <p className={styles.muted}>
                    发送结果尚未确认。重试会沿用原消息；改写后会作为一条新消息发送。
                  </p>
                  <div className={styles.actions}>
                    <Button
                      type="button"
                      disabled={loading}
                      onClick={() => void send(intent.resolve, intent)}
                    >
                      重试发送
                    </Button>
                    <Button
                      type="button"
                      className="secondary"
                      disabled={loading}
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
                    disabled={
                      loading || sending || withdrawing || !draft.trim()
                    }
                  >
                    {sending ? "正在发送…" : "发送消息"}
                  </Button>
                  {props.admin && (
                    <Button
                      type="button"
                      className="secondary"
                      disabled={loading || sending || !draft.trim()}
                      onClick={() => void send(true)}
                    >
                      回复并标记已解决
                    </Button>
                  )}
                </div>
              )}
              {sent && (
                <p className={styles.sent} role="status">
                  消息已发送。
                </p>
              )}
              <p className={styles.muted}>
                请在此查看回复，暂不发送聊天邮件提醒。
              </p>
            </form>
          ) : (
            <Notice>
              {view.moderationStatus === "WITHDRAWN"
                ? "反馈已撤回，问题内容和私有对话已清理。"
                : view.moderationStatus === "WITHDRAWAL_REQUESTED"
                  ? "撤回申请已提交，私有对话已清理；已公开的原问题仍需管理员处理。"
                  : view.participant?.kind === "GUEST" &&
                      !["WITHDRAWN", "WITHDRAWAL_REQUESTED", "SPAM"].includes(
                        view.moderationStatus,
                      )
                    ? "访客单次反馈：仅收件，不建立聊天。若对方留下联系方式，可由你自行联系。"
                    : "这条反馈已关闭对话，暂不能新增消息。"}
            </Notice>
          )}
          {!props.admin &&
            !["WITHDRAWN", "WITHDRAWAL_REQUESTED"].includes(
              view.moderationStatus,
            ) && (
              <div className={styles.withdrawal}>
                {confirmWithdrawal ? (
                  <>
                    <p>
                      确认撤回这条反馈？问题和私有对话将被清理；已公开的原问题需要管理员进一步处理。此操作无法恢复。
                    </p>
                    <div className={styles.actions}>
                      <Button
                        type="button"
                        className="secondary"
                        disabled={loading || sending || withdrawing}
                        onClick={() => void withdraw()}
                      >
                        {withdrawing ? "正在撤回…" : "确认撤回"}
                      </Button>
                      <Button
                        type="button"
                        className="secondary"
                        disabled={withdrawing}
                        onClick={() => setConfirmWithdrawal(false)}
                      >
                        取消撤回
                      </Button>
                    </div>
                  </>
                ) : (
                  <button
                    className={styles.textButton}
                    disabled={loading || sending || withdrawing}
                    onClick={() => setConfirmWithdrawal(true)}
                  >
                    撤回这条反馈
                  </button>
                )}
              </div>
            )}
        </>
      )}
    </section>
  );
}
