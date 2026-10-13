"use client";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
const schema = z.object({
  email: z.string(),
  password: z.string().max(128),
  displayName: z.string().max(80),
});
type Values = z.infer<typeof schema>;
const labels: Record<string, string> = {
  login: "欢迎回来。",
  register: "认识你的新伙伴。",
  "forgot-password": "找回密码",
  "reset-password": "设置新密码",
  "verify-email": "验证邮箱",
};
export function AuthPage({ mode }: { mode: string }) {
  const query = useSearchParams();
  const router = useRouter();
  const client = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [verifying, setVerifying] = useState(false);
  // 单一表单类型保留稳定字段，按页面用途执行边界校验。
  const formSchema = schema.superRefine((values, context) => {
    if (mode !== "reset-password" && !z.email().safeParse(values.email).success)
      context.addIssue({
        code: "custom",
        path: ["email"],
        message: "请输入有效的邮箱地址。",
      });
    if (
      ["register", "login", "reset-password"].includes(mode) &&
      values.password.length < 10
    )
      context.addIssue({
        code: "custom",
        path: ["password"],
        message: "密码至少 10 个字符。",
      });
  });
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(formSchema),
    defaultValues: { displayName: "", password: "", email: "" },
  });
  async function submit(values: Values) {
    setError(undefined);
    setSuccess("");
    try {
      if (mode === "login" || mode === "register") {
        await api(
          `/auth/${mode}`,
          "POST",
          mode === "register"
            ? values
            : { email: values.email, password: values.password },
        );
        if (mode === "register") {
          setSuccess("账号已创建。请检查邮箱完成验证，再返回登录。");
          return;
        }
        await client.invalidateQueries({ queryKey: ["me"] });
        const next = query.get("returnTo") ?? query.get("next");
        router.push(
          next?.startsWith("/") && !next.startsWith("//") ? next : "/dashboard",
        );
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
        setSuccess("如邮箱符合条件，邮件将发送至该地址。请检查收件箱。");
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
      <div className="narrow">
        <Heading
          eyebrow="YOUR ACCOUNT / 你的账号"
          title={labels[mode] ?? "账号"}
        >
          账号用于管理资源。桌面的聊天与记忆继续保存在本地。
        </Heading>
        <div className="panel">
          {mode === "verify-email" && query.get("token") ? (
            <Button disabled={verifying || !!success} onClick={confirm}>
              {verifying ? "正在验证…" : "确认验证邮箱"}
            </Button>
          ) : (
            <form onSubmit={handleSubmit(submit)} noValidate>
              {mode !== "reset-password" && (
                <Field label="邮箱">
                  <input
                    type="email"
                    autoComplete="email"
                    {...register("email")}
                  />
                  {errors.email && (
                    <small className="form-error">{errors.email.message}</small>
                  )}
                </Field>
              )}
              {mode === "register" && (
                <Field label="昵称">
                  <input autoComplete="nickname" {...register("displayName")} />
                </Field>
              )}
              {["login", "register", "reset-password"].includes(mode) && (
                <Field label="密码" hint="至少 10 个字符。">
                  <input
                    type="password"
                    autoComplete={
                      mode === "login" ? "current-password" : "new-password"
                    }
                    {...register("password")}
                  />
                  {errors.password && (
                    <small className="form-error">
                      {errors.password.message}
                    </small>
                  )}
                </Field>
              )}
              <Button disabled={isSubmitting} type="submit">
                {isSubmitting
                  ? "正在处理…"
                  : mode === "login"
                    ? "登录"
                    : mode === "register"
                      ? "创建账号"
                      : mode === "reset-password"
                        ? "更新密码"
                        : "发送邮件"}
              </Button>
            </form>
          )}
          {error !== undefined && <Notice error={error} />}{" "}
          {success && <Notice>{success}</Notice>}
          <div className="auth-links">
            <Link href={mode === "login" ? "/register" : "/login"}>
              {mode === "login" ? "创建账号" : "返回登录"}
            </Link>
            <Link href="/forgot-password">忘记密码？</Link>
          </div>
        </div>
        <p className="legal-note">
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
