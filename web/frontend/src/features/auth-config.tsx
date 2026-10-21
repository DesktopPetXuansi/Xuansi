"use client";
import { Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import type { AuthConfig } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";

// 提示与校验读取同一服务端配置，避免再各自写死密码门槛。
export function useAuthConfig() {
  return useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api<AuthConfig>("/auth/config"),
    staleTime: 60000,
  });
}

export function passwordHint(policy: AuthConfig["password"]) {
  return `${policy.minLength} 至 ${policy.maxLength} 个字符。`;
}

export function passwordError(
  value: string,
  policy: AuthConfig["password"],
  creating = true,
) {
  // 字符串迭代按Unicode码点计数，与Go一致，避免Emoji被算作两个字符。
  const length = [...value].length;
  if (!length) return "请输入密码。";
  if (creating && length < policy.minLength)
    return `密码至少 ${policy.minLength} 个字符。`;
  if (length > policy.maxLength) return `密码最多 ${policy.maxLength} 个字符。`;
}

export function LocalMailbox({ config, purpose }: { config?: AuthConfig; purpose?: "registration" }) {
  if (config?.email.mode !== "LOCAL_MAILBOX" || !config.email.inboxUrl)
    return null;
  return (
    <Notice>
      <p>验证邮件会进入本地收件箱，不会发送到真实邮箱。</p>
	      <p>{purpose === "registration"
	        ? "邮件内含 6 位验证码，请回到本页完成注册。"
	        : "邮件内含有效期为 1 小时的验证链接，无需输入验证码。"}</p>
      <a
        className="quiet-link"
        href={safeUrl(config.email.inboxUrl)}
        target="_blank"
        rel="noopener noreferrer"
      >
        打开本地收件箱
      </a>
    </Notice>
  );
}
