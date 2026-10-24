"use client";

import { Button, Field, Notice } from "@/components/ui";
import type { User } from "@/lib/types";
import { usePublicFeedback } from "./use-public-feedback";
import Link from "next/link";
import { useMe } from "../identity/session";
import { FeedbackConfirmation } from "./feedback-confirmation";
import styles from "./public-feedback.module.css";

export function PublicFeedback() {
  const identity = useMe();
  // 身份切换重建私有草稿；读取失败不擅自降级成访客提交。
  return (
    <PublicFeedbackForm
      key={identity.data?.id ?? "guest"}
      user={identity.data}
      checking={identity.isPending}
      identityError={identity.error}
      retryIdentity={() => void identity.refetch()}
    />
  );
}

// 表单只在用户操作时请求；正文保留在内存，重试复用同一份输入与幂等编号。
function PublicFeedbackForm({
  user,
  checking,
  identityError,
  retryIdentity,
}: {
  user?: User | null;
  checking: boolean;
  identityError: unknown;
  retryIdentity: () => void;
}) {
  const identityBlocked = checking || identityError != null;
  const {
    description,
    setDescription,
    contact,
    setContact,
    publicConsent,
    setPublicConsent,
    busy,
    error,
    attempt,
    receipt,
    focusNewDraft,
    accountId,
    startAgain,
    submit,
  } = usePublicFeedback({ user, identityBlocked, retryIdentity });
  return (
    <section
      id="feedback"
      className={styles.section}
      aria-labelledby="feedback-title"
    >
      <div>
        <p className="eyebrow">一起把玄司做得更好</p>
        <h2 id="feedback-title">有问题或建议？</h2>
        <p>
          {user
            ? `将以「${user.displayName}」提交，可在“我的反馈”继续沟通。`
            : "不用注册，写下遇到的问题或希望增加的功能即可。"}
        </p>
        <p>默认仅开发者可见。请勿填写密码、API 密钥等敏感内容。</p>
        {user ? (
          <Link className="quiet-link" href="/dashboard/feedback">
            查看我的反馈 →
          </Link>
        ) : (
          <p>
            匿名反馈仅进入开发者收件箱，不在本浏览器保存历史或建立聊天。登录后提交可持续沟通。
          </p>
        )}
      </div>
      <div className={styles.form}>
        {receipt ? (
          <FeedbackConfirmation
            receipt={receipt}
            account={accountId !== null}
            onStartAgain={startAgain}
          />
        ) : (
          <form
            className={styles.form}
            onSubmit={(event) => void submit(event)}
            aria-busy={busy}
          >
            <Field label="问题或建议">
              <textarea
                ref={focusNewDraft}
                required
                maxLength={4000}
                rows={4}
                value={description}
                disabled={busy || identityBlocked || attempt !== undefined}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="遇到了什么？可以写下操作步骤，或你期待的功能……"
              />
            </Field>
            <details className={styles.options}>
              <summary>
                {user ? "联系方式与公开选项（选填）" : "联系方式（选填）"}
              </summary>
              <div className={styles.optionFields}>
                <Field
                  label="联系方式（选填）"
                  hint="仅开发者可见，方便需要时联系你。"
                >
                  <input
                    maxLength={160}
                    value={contact}
                    disabled={busy || identityBlocked || attempt !== undefined}
                    onChange={(event) => setContact(event.target.value)}
                    placeholder="邮箱、QQ 或其他联系方式"
                  />
                </Field>
                {user && (
                  <label className={styles.consent}>
                    <input
                      type="checkbox"
                      checked={publicConsent}
                      disabled={
                        busy || identityBlocked || attempt !== undefined
                      }
                      onChange={(event) =>
                        setPublicConsent(event.target.checked)
                      }
                    />
                    <span>
                      我同意审核后将反馈正文公开到 GitHub，联系方式不公开。
                    </span>
                  </label>
                )}
              </div>
            </details>
            {checking && <Notice>正在确认登录状态…</Notice>}
            {identityError != null && (
              <>
                <Notice error={identityError} />
                <Button
                  type="button"
                  className="secondary"
                  onClick={retryIdentity}
                >
                  重试登录状态
                </Button>
              </>
            )}
            {error !== undefined && <Notice error={error} />}
            {attempt && !busy && (
              <small>
                草稿已保留。为避免重复提交，重试会发送相同内容；确认收到后可继续提交其他反馈。
              </small>
            )}
            <div>
              <Button type="submit" disabled={busy || identityBlocked}>
                {busy ? "正在提交…" : attempt ? "重试这条反馈" : "提交反馈"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
