"use client";
import { useMe } from "@/components/navigation";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { replaceSession } from "./identity/session";
import { api } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { passwordError, passwordHint, useAuthConfig } from "./auth-config";
export function Account() {
  const router = useRouter();
  const me = useMe();
  const cache = useQueryClient();
  const config = useAuthConfig();
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(
    event: React.FormEvent<HTMLFormElement>,
    password = false,
  ) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (password) {
      if (!config.data) return;
      const problem = passwordError(
        String(form.get("password")),
        config.data.password,
      );
      if (problem) {
        setError(new Error(problem));
        setSuccess("");
        return;
      }
    }
    setBusy(true);
    setError(undefined);
    try {
      await api(
        password ? "/me/password" : "/me",
        password ? "PUT" : "PATCH",
        password
          ? {
              currentPassword: String(form.get("currentPassword")),
              password: String(form.get("password")),
            }
          : { displayName: String(form.get("displayName")) },
      );
      await cache.invalidateQueries({ queryKey: ["me"] });
      setSuccess(password ? "密码已更新。" : "资料已保存。");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await api("/auth/logout", "POST", {});
      await replaceSession(cache, false);
      router.push("/login");
    } catch (cause) {
      setError(cause);
    }
  }
  return (
    <>
      <Heading title="账号设置">管理网站资料与登录信息。</Heading>
      <div className="grid-two">
        <form className="panel" onSubmit={(event) => submit(event)}>
          <h3>个人资料</h3>
          <p>
            {me.data?.email} · {me.data?.emailVerified ? "已验证" : "待验证"}
          </p>
          <Field label="昵称">
            <input
              name="displayName"
              defaultValue={me.data?.displayName}
              required
              maxLength={80}
            />
          </Field>
          <Button disabled={busy}>保存资料</Button>
        </form>
        <form
          className="panel"
          onSubmit={(event) => submit(event, true)}
          noValidate
        >
          <h3>修改密码</h3>
          <Field label="当前密码">
            <input
              type="password"
              name="currentPassword"
              autoComplete="current-password"
              required
            />
          </Field>
          <Field
            label="新密码"
            hint={config.data && passwordHint(config.data.password)}
          >
            <input
              type="password"
              name="password"
              autoComplete="new-password"
              required
            />
          </Field>
          {config.error && <Notice error={config.error} />}
          <Button disabled={busy || !config.data}>更新密码</Button>
        </form>
      </div>
      {error !== undefined && <Notice error={error} />}{" "}
      {success && <Notice>{success}</Notice>}
      <Button className="secondary" style={{ marginTop: 24 }} onClick={logout}>
        退出登录
      </Button>
    </>
  );
}
