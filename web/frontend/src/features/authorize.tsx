"use client";
import { useMe } from "@/components/navigation";
import { Button, Heading, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
export function Authorize() {
  const params = useSearchParams();
  // 权限说明直接来自此次申请；旧只读授权保持原有文案。
  const scopes = (params.get("scope") ?? "").trim().split(/\s+/);
  const upload = scopes.includes("resources:write");
  const historyRead = scopes.includes("history:read");
  const historyWrite = scopes.includes("history:write");
  const validScope =
    scopes.includes("resources:read") &&
    (!historyWrite || historyRead) &&
    new Set(scopes).size === scopes.length &&
    scopes.every((scope) =>
      ["resources:read", "resources:write", "history:read", "history:write"].includes(scope),
    );
  const me = useMe();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  async function allow() {
    setBusy(true);
    try {
      const csrf = await api<{ token: string }>("/auth/csrf");
      const body = new URLSearchParams(params.toString());
      body.set("consent", "approve");
      body.set("approve", "true");
      const response = await fetch("/oauth/authorize", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRF-Token": csrf.token,
        },
        credentials: "include",
        body,
      });
      const result: unknown = await response.json();
      const parsed = z
        .object({ data: z.object({ redirectUrl: z.string() }) })
        .safeParse(result);
      if (!response.ok || !parsed.success)
        throw new Error("授权未完成，请从客户端重新发起。");
      // 授权码只能交给最初请求的回环回调，避免开放重定向。
      const redirect = new URL(parsed.data.data.redirectUrl);
      const expected = new URL(params.get("redirect_uri") ?? "http://invalid/");
      if (
        redirect.origin !== expected.origin ||
        redirect.pathname !== "/oauth/callback" ||
        !["127.0.0.1", "[::1]"].includes(redirect.hostname)
      )
        throw new Error("客户端回调地址不符合安全要求。");
      window.location.assign(safeUrl(redirect.href));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="container">
      <div className="narrow">
        <Heading
          title={historyWrite ? "允许客户端同步形象历史？" : historyRead ? "允许客户端读取历史？" : upload ? "允许客户端上传模型？" : "允许客户端读取资源？"}
        >
          请确认这是你刚刚在桌面客户端发起的操作。
        </Heading>
        <div className="panel">
          <h3>desktop-ai-pet</h3>
          <p>此次申请的权限：</p>
          <ul className="consent-permissions">
            <li>资源读取：查看收藏、资源清单与下载资源包。</li>
            {upload && <li>模型上传：上传你选择的本地模型，设为当前版本并加入收藏。</li>}
            {historyRead && <li>历史读取：读取账号中的形象使用记录和下载记录。</li>}
            {historyWrite && <li>历史同步与删除：保存你此后成功使用的形象记录，并允许删除历史。不自动上传开启同步以前的本机记录。</li>}
          </ul>
          <p className="muted">
            不会获取你的密码，不会上传聊天、截图、录音或本地记忆。你可以随时在会话与授权页面撤销。
          </p>
          {!validScope ? (
            <Notice>授权权限无效，请从客户端重新发起。</Notice>
          ) : me.isPending ? (
            <Notice>正在检查账号…</Notice>
          ) : me.error ? (
            <Notice error={me.error} />
          ) : !me.data ? (
            <Link
              className="button-link"
              href={`/login?returnTo=${encodeURIComponent(`/authorize?${params}`)}`}
            >
              登录后继续
            </Link>
          ) : (
            <div className="actions">
              <Button disabled={busy} onClick={allow}>
                {busy ? "正在授权…" : historyWrite ? "允许同步形象历史" : historyRead ? "允许读取历史" : upload ? "允许上传模型" : "允许读取资源"}
              </Button>
              <Link href="/dashboard/sessions" className="quiet-link">
                暂不授权
              </Link>
            </div>
          )}
          {error !== undefined && <Notice error={error} />}
        </div>
      </div>
    </div>
  );
}
