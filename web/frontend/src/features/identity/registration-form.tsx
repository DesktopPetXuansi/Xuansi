"use client";

import { api, ApiError } from "@/lib/api";
import type { RegistrationInput } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { passwordError, useAuthConfig } from "../auth-config";
import { useRegistrationCode } from "./registration-code";
import { returnPath } from "./return-path";
import { replaceSession } from "./session";

type Values = Pick<RegistrationInput, "email" | "code" | "password">;

// 注册事件集中处理校验与会话切换，页面只负责字段及可访问性呈现。
export function useRegistrationForm() {
  const query = useSearchParams();
  const destination = returnPath(query.get("returnTo") ?? query.get("next"));
  const router = useRouter();
  const client = useQueryClient();
  const config = useAuthConfig();
  const challenge = useRegistrationCode();
  const [error, setError] = useState<unknown>();
  const submitting = useRef(false);
  const {
    register,
    handleSubmit,
    getValues,
    setValue,
    setError: fieldError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    defaultValues: { email: "", code: "", password: "" },
  });
  const busy = isSubmitting || challenge.sending;

  function validEmail() {
    const email = getValues("email").trim();
    if (!z.email().safeParse(email).success) {
      fieldError(
        "email",
        { message: "请输入有效的邮箱地址。" },
        { shouldFocus: true },
      );
      return;
    }
    clearErrors("email");
    return email;
  }

  async function sendCode() {
    if (busy) return;
    const email = validEmail();
    if (!email) return;
    setError(undefined);
    clearErrors("code");
    try {
      if (await challenge.send(email)) setValue("code", "");
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.code === "EMAIL_ALREADY_REGISTERED"
      )
        fieldError("email", {
          message: "这个邮箱已注册，请直接登录或找回密码。",
        });
      else setError(cause);
    }
  }

  async function submit(values: Values) {
    if (submitting.current || challenge.sending || !config.data) return;
    clearErrors();
    setError(undefined);
    const email = validEmail();
    if (!email) return;
    let invalid = false;
    if (!challenge.receipt) {
      fieldError("code", { message: "请先获取邮箱验证码。" });
      invalid = true;
    } else if (!/^[0-9]{6}$/.test(values.code)) {
      fieldError("code", { message: "请输入邮件中的 6 位数字验证码。" });
      invalid = true;
    }
    const passwordMessage = passwordError(
      values.password,
      config.data.password,
    );
    if (passwordMessage) {
      fieldError("password", { message: passwordMessage });
      invalid = true;
    }
    if (invalid || !challenge.receipt) return;
    submitting.current = true;
    try {
      await api("/auth/registrations", "POST", {
        email,
        password: values.password,
        code: values.code,
        challengeId: challenge.receipt.challengeId,
      } satisfies RegistrationInput);
      await replaceSession(client, true);
      console.debug("[注册] 账号已创建并同步登录状态");
      router.replace(destination);
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.code === "REGISTRATION_CODE_INVALID"
      )
        fieldError(
          "code",
          { message: "验证码错误或已失效，请检查后重试，或重新获取。" },
          { shouldFocus: true },
        );
      else if (
        cause instanceof ApiError &&
        cause.code === "EMAIL_ALREADY_REGISTERED"
      )
        fieldError("email", {
          message: "这个邮箱已注册，请直接登录或找回密码。",
        });
      else setError(cause);
    } finally {
      submitting.current = false;
    }
  }

  function changeEmail() {
    challenge.reset();
    setValue("code", "");
    clearErrors(["email", "code"]);
    setError(undefined);
  }

  return {
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
  };
}
