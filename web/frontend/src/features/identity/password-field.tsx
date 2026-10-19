"use client";

import { Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";
import styles from "./auth.module.css";

export function PasswordField({
  registration,
  autoComplete,
  hint,
  error,
  recoveryHref,
}: {
  registration: UseFormRegisterReturn<"password">;
  autoComplete: "current-password" | "new-password";
  hint?: string;
  error?: string;
  recoveryHref?: string;
}) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const description = [error && `${id}-error`, hint && `${id}-hint`]
    .filter(Boolean).join(" ") || undefined;

  return <div className={`field ${styles.passwordField}`}>
    <div className={styles.fieldHeading}>
      <label htmlFor={id}>{autoComplete === "new-password" ? "设置密码" : "密码"}</label>
      {recoveryHref && <Link className={styles.recovery} href={recoveryHref}>忘记密码？</Link>}
    </div>
    <div className={styles.passwordControl}>
      <input id={id} type={visible ? "text" : "password"} autoComplete={autoComplete}
        placeholder={autoComplete === "new-password" ? "请设置登录密码" : "请输入密码"}
        aria-invalid={!!error} aria-describedby={description} {...registration} />
      {/* 独立按钮不放入 label，也不提交表单；切换只改变可见性，保留表单值。 */}
      <button type="button" className={styles.visibility} aria-label={visible ? "隐藏密码" : "显示密码"}
        aria-controls={id} aria-pressed={visible} onClick={() => {
          setVisible(!visible);
          console.debug("[账号表单] 已切换密码可见状态");
        }}>
        {visible ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
        <span>{visible ? "隐藏" : "显示"}</span>
      </button>
    </div>
    {error && <small id={`${id}-error`} className="form-error" role="alert">{error}</small>}
    {hint && <small id={`${id}-hint`}>{hint}</small>}
  </div>;
}
