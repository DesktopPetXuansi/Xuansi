"use client";

import { Button, Heading, Notice } from "@/components/ui";
import Link from "next/link";
import { LocalMailbox, passwordHint } from "../auth-config";
import { AuthLinks } from "./auth-links";
import styles from "./auth.module.css";
import registrationStyles from "./registration.module.css";
import { PasswordField } from "./password-field";
import { useRegistrationForm } from "./registration-form";

export function RegistrationPage() {
  const {
    destination,
    config,
    challenge,
    error,
    register,
    handleSubmit,
    getValues,
    errors,
    isSubmitting,
    busy,
    sendCode,
    submit,
    changeEmail,
  } = useRegistrationForm();

  return (
    <div className="container">
      <div className={styles.page}>
        <Heading eyebrow="YOUR ACCOUNT / 你的账号" title="创建账号">
          验证邮箱、设置密码，一次完成注册。
        </Heading>
        <div className={`panel ${styles.card}`}>
          {config.isPending && <Notice>正在加载账号配置…</Notice>}
          {config.error && <Notice error={config.error} />}
          <form
            onSubmit={(event) => void handleSubmit(submit)(event)}
            noValidate
          >
            <div className={registrationStyles.emailRow}>
              <div className={`field ${registrationStyles.emailField}`}>
                <label htmlFor="registration-email">邮箱</label>
                <input
                  id="registration-email"
                  type="email"
                  autoComplete="email"
                  placeholder="请输入邮箱地址"
                  readOnly={isSubmitting}
                  aria-invalid={!!errors.email}
                  aria-describedby={
                    errors.email ? "registration-email-error" : undefined
                  }
                  {...register("email", {
                    onChange: changeEmail,
                  })}
                />
              </div>
              <Button
                type="button"
                className={registrationStyles.send}
                disabled={busy || challenge.remaining > 0 || !config.data}
                onClick={sendCode}
              >
                {challenge.sending
                  ? "正在发送…"
                  : challenge.remaining > 0
                    ? `${challenge.remaining} 秒后重发`
                    : challenge.receipt
                      ? "重新获取"
                      : "获取验证码"}
              </Button>
            </div>
            {errors.email && (
              <small
                id="registration-email-error"
                className={`form-error ${registrationStyles.emailError}`}
                role="alert"
              >
                {errors.email.message}
              </small>
            )}
            {challenge.receipt && (
              <p className={registrationStyles.delivery} role="status">
                验证码邮件已排队发送至 {getValues("email").trim()}，10
                分钟内有效。请检查收件箱和垃圾邮件。
              </p>
            )}
            <div className="field">
              <label htmlFor="registration-code">邮件验证码</label>
              <input
                id="registration-code"
                className={registrationStyles.code}
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="6 位数字"
                readOnly={isSubmitting}
                aria-invalid={!!errors.code}
                aria-describedby={
                  errors.code ? "registration-code-error" : undefined
                }
                {...register("code")}
              />
              {errors.code && (
                <small
                  id="registration-code-error"
                  className="form-error"
                  role="alert"
                >
                  {errors.code.message}
                </small>
              )}
            </div>
            <PasswordField
              registration={register("password")}
              autoComplete="new-password"
              error={errors.password?.message}
              hint={config.data && passwordHint(config.data.password)}
            />
            {error !== undefined && <Notice error={error} />}
            <Button
              className={styles.submit}
              type="submit"
              disabled={busy || !config.data}
            >
              {isSubmitting ? "正在注册并登录…" : "注册并登录"}
            </Button>
          </form>
          {challenge.receipt && (
            <LocalMailbox config={config.data} purpose="registration" />
          )}
          <AuthLinks
            mode="register"
            destination={destination}
            complete={false}
          />
        </div>
        <p className={styles.backHome}>
          <Link href="/" className="quiet-link">
            返回首页
          </Link>
        </p>
        <p className={styles.legal}>
          继续即表示你已阅读{" "}
          <Link href="/terms" className="quiet-link">
            使用条款
          </Link>{" "}
          和{" "}
          <Link href="/privacy" className="quiet-link">
            隐私说明
          </Link>
          。
        </p>
      </div>
    </div>
  );
}
