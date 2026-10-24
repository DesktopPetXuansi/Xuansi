"use client";

import { Button, Notice } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { FeedbackThread } from "@/lib/types";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMe } from "../identity/session";
import {
  forgetCredentials,
  type FeedbackCredentials,
} from "./management-storage";

// 关联只能由旧管理权限持有人主动发起，账号身份由服务器会话确认。
export function FeedbackClaim({
  credentials,
  busy,
  begin,
  end,
  onClaimed,
}: {
  credentials: FeedbackCredentials;
  busy: boolean;
  begin: () => boolean;
  end: () => void;
  onClaimed: () => void;
}) {
  const me = useMe();
  const router = useRouter();
  const [error, setError] = useState<unknown>();
  if (!me.data || me.error || !credentials.id) return null;
  const accountId = me.data.id;
  async function claim() {
    if (!begin()) return;
    setError(undefined);
    try {
      const thread = await api<FeedbackThread>(
        `/me/feedback/${credentials.id}/claim`,
        "POST",
        {
          managementToken: credentials.managementToken,
        },
        false,
        { expectedAccountId: accountId },
      );
      if (thread.id !== credentials.id)
        throw new Error("无法确认关联结果，请重试。");
      forgetCredentials(credentials.idempotencyKey);
      onClaimed();
      // replace移除当前页面的旧凭据片段，不将令牌带入账号会话地址。
      router.replace(`/dashboard/feedback?id=${thread.id}`);
      console.debug("[反馈关联] 已转入账号会话");
    } catch (failure) {
      setError(failure);
      if (
        failure instanceof ApiError &&
        ([401, 403].includes(failure.status) ||
          failure.code === "ACCOUNT_CHANGED")
      )
        void me.refetch();
      console.warn("[反馈关联] 关联未确认，可重新尝试");
    } finally {
      end();
    }
  }
  return (
    <div>
      <p>
        可将这条旧反馈关联到当前账号「{me.data.displayName}
        」。关联后，原管理链接将失效；历史匿名消息仍显示为访客。
      </p>
      <Button
        className="secondary"
        disabled={busy}
        onClick={() => void claim()}
      >
        关联到我的账号
      </Button>
      {error !== undefined && <Notice error={error} />}
    </div>
  );
}
