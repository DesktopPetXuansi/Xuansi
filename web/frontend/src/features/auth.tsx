"use client";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { replaceSession } from "./identity/session";
import { authHref, returnPath } from "./identity/return-path";
import { AuthLinks } from "./identity/auth-links";
import { PasswordField } from "./identity/password-field";
import styles from "./identity/auth.module.css";
import { api } from "@/lib/api";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import {
  LocalMailbox,
  passwordError,
  passwordHint,
  useAuthConfig,
} from "./auth-config";
const schema = z.object({
  email: z.string(),
  password: z.string(),
});
type Values = z.infer<typeof schema>;
const labels: Record<string, string> = {
  login: "欢迎回来",
  "forgot-password": "找回密码",
  "reset-password": "设置新密码",
  "verify-email": "验证邮箱",
};
const descriptions: Record<string, string> = {
  login: "登录后，接着使用你的收藏与形象历史。",
  "forgot-password": "输入注册邮箱，获取重置密码的链接。",
  "reset-password": "设置新的登录密码，完成后重新登录。",
  "verify-email": "输入注册邮箱，重新获取验证邮件。",
};
export function AuthPage({ mode }: { mode: string }) {
  const query = useSearchParams();
  const destination = returnPath(query.get("returnTo") ?? query.get("next"));
  const router = useRouter();
  const client = useQueryClient();
  const config = useAuthConfig();
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [verifying, setVerifying] = useState(false);
  const confirmation = mode === "verify-email" && !!query.get("token");
  const complete = !!success && (mode === "reset-password" || confirmation);
  // 单一表单类型保留稳定字段，按页面用途执行边界校验。
  const formSchema = schema.superRefine((values, context) => {
    if (mode !== "reset-password" && !z.email().safeParse(values.email).success)
      context.addIssue({
        code: "custom",
        path: ["email"],
        message: "请输入有效的邮箱地址。",
      });
    if (["login", "reset-password"].includes(mode) && config.data) {
      const message = passwordError(
        values.password,
        config.data.password,
        mode !== "login",
      );
      if (message)
        context.addIssue({ code: "custom", path: ["password"], message });
    }
  });
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(formSchema),
    defaultValues: { password: "", email: "" },
  });
  async function submit(values: Values) {
    if (!config.data) return;
    setError(undefined);
    setSuccess("");
    try {
      if (mode === "login") {
        await api("/auth/login", "POST", { email: values.email, password: values.password });
        await replaceSession(client, true);
        console.debug("[账号] 登录成功，返回原站内页面");
        router.replace(destination);
      } else if (mode === "reset-password") {
        await api("/auth/password-resets/confirm", "POST", {
          token: query.get("token"),
          password: values.password,
        });
        setSuccess("密码已更新，请使用新密码登录。");
      } else {
        await api(
          mode === "verify-email"
            ? "/auth/email-verifications"
            : "/auth/password-resets",
          "POST",
          { email: values.email },
        );
        setSuccess(
          config.data.email.mode === "LOCAL_MAILBOX"
            ? "如邮箱符合条件，验证邮件会进入下方本地收件箱。请打开邮件中的链接。"
            : "如邮箱符合条件，邮件已排队发送。请检查收件箱和垃圾邮件。邮件内含验证链接。",
        );
      }
    } catch (cause) {
      setError(cause);
    }
  }
  async function confirm() {
    setVerifying(true);
    setError(undefined);
    try {
      await api("/auth/email-verifications/confirm", "POST", {
        token: query.get("token"),
      });
      await client.invalidateQueries({ queryKey: ["me"] });
      setSuccess("邮箱验证完成，现在可以上传资源。");
    } catch (cause) {
      setError(cause);
    } finally {
      setVerifying(false);
    }
  }
  return (
    <div className="container">
      <div className={styles.page}>
        <Heading
          eyebrow="YOUR ACCOUNT / 你的账号"
          title={labels[mode] ?? "账号"}
        >
          {confirmation ? "确认邮箱后，即可上传与分享作品。" : descriptions[mode]}
        </Heading>
        <div className={`panel ${styles.card}`}>
          {config.isPending && <Notice>正在加载账号配置…</Notice>}
          {config.error && <Notice error={config.error} />}
          {!complete && (confirmation ? (
            <Button className={styles.submit} disabled={verifying} onClick={confirm}>
              {verifying ? "正在验证…" : "确认验证邮箱"}
            </Button>
          ) : (
            <form onSubmit={handleSubmit(submit)} noValidate>
              {mode !== "reset-password" && (
                <Field label="邮箱">
                  <input
                    type="email"
                    id="auth-email"
                    placeholder="请输入邮箱地址"
                    autoComplete={mode === "login" ? "username" : "email"}
                    aria-invalid={!!errors.email}
                    aria-describedby={errors.email ? "auth-email-error" : undefined}
                    {...register("email")}
                  />
                  {errors.email && (
                    <small id="auth-email-error" className="form-error" role="alert">{errors.email.message}</small>
                  )}
                </Field>
              )}
              {["login", "reset-password"].includes(mode) && (
                <PasswordField
                  registration={register("password")}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  recoveryHref={mode === "login" ? authHref("/forgot-password", destination) : undefined}
                  error={errors.password?.message}
                  hint={
                    mode === "login"
                      ? undefined
                      : config.data && passwordHint(config.data.password)
                  }
                />
              )}
              {error !== undefined && <Notice error={error} />}
              <Button className={styles.submit} disabled={isSubmitting || !config.data} type="submit">
                {isSubmitting
                  ? "正在处理…"
                  : mode === "login"
                    ? "登录"
                      : mode === "reset-password"
                        ? "更新密码"
                        : "发送邮件"}
              </Button>
            </form>
          ))}
          {confirmation && error !== undefined && <Notice error={error} />}
          {success && <Notice>{success}</Notice>}
          {(mode === "verify-email" || (!!success && mode === "forgot-password")) &&
            <LocalMailbox config={config.data} />}
          <AuthLinks mode={mode} destination={destination} complete={complete} />
        </div>
        <p className={styles.backHome}><Link href="/" className="quiet-link">返回首页</Link></p>
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
