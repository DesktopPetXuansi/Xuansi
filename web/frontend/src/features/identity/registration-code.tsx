"use client";

import { api, ApiError } from "@/lib/api";
import type { RegistrationCodeReceipt } from "@/lib/types";
import { useEffect, useRef, useState } from "react";
import { z } from "zod";

// 收据控制后续注册权限与冷却时间，只有结构和时间关系有效时才能使用。
const receiptSchema = z
  .object({
    challengeId: z.uuid(),
    expiresAt: z.iso.datetime({ offset: true }),
    resendAt: z.iso.datetime({ offset: true }),
  })
  .refine((value) => Date.parse(value.expiresAt) > Date.parse(value.resendAt));

// 邮箱编辑立即使当前挑战失效；请求编号同时隔离晚到的旧邮箱响应。
export function useRegistrationCode() {
  const [receipt, setReceipt] = useState<RegistrationCodeReceipt>();
  const [sending, setSending] = useState(false);
  const [now, setNow] = useState(0);
  const generation = useRef(0);
  const pending = useRef(false);
  const resendAt = receipt ? Date.parse(receipt.resendAt) : 0;
  const remaining = Math.max(0, Math.ceil((resendAt - now) / 1000));

  // 只同步浏览器时钟；切换挑战或离开页面时清理计时器，无后台轮询。
  useEffect(() => {
    if (!resendAt || Date.now() >= resendAt) return;
    const timer = window.setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= resendAt) window.clearInterval(timer);
    }, 500);
    return () => window.clearInterval(timer);
  }, [resendAt]);

  function reset() {
    generation.current++;
    setReceipt(undefined);
  }

  async function send(email: string) {
    if (pending.current || (receipt && Date.now() < resendAt)) return;
    pending.current = true;
    setSending(true);
    const requestGeneration = generation.current;
    try {
      const response = await api<unknown>("/auth/registration-codes", "POST", {
        email,
      });
      if (requestGeneration !== generation.current) return;
      const parsed = receiptSchema.safeParse(response);
      if (!parsed.success) {
        setReceipt(undefined);
        console.warn("[注册] 验证码服务返回无效收据");
        throw new ApiError("验证码请求结果无效，请重新获取。", 502);
      }
      const result = parsed.data;
      setNow(Date.now());
      setReceipt(result);
      console.debug("[注册] 验证码请求已受理");
      return result;
    } catch (error) {
      if (requestGeneration === generation.current) throw error;
    } finally {
      pending.current = false;
      setSending(false);
    }
  }

  return { receipt, sending, remaining, reset, send };
}
