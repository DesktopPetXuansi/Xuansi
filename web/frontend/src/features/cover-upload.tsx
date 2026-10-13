"use client";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import type { Upload } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function CoverUpload({ id }: { id: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [uploadId, setUploadId] = useState("");
  const status = useQuery({
    queryKey: ["cover-upload", uploadId],
    queryFn: () => api<Upload>(`/uploads/${uploadId}`),
    enabled: !!uploadId,
    refetchInterval: (query) =>
      query.state.data &&
      ["READY", "FAILED", "CANCELLED", "EXPIRED"].includes(
        query.state.data.status,
      )
        ? false
        : 2000,
  });
  const cache = useQueryClient();
  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = new FormData(event.currentTarget).get("cover");
    if (!(file instanceof File) || !file.size) return;
    setBusy(true);
    setError(undefined);
    try {
      const session = await api<Upload>("/uploads", "POST", {
        resourceId: id,
        purpose: "COVER",
        filename: file.name,
        expectedBytes: file.size,
      });
      if (session.method !== "PUT") throw new Error("上传服务未提供PUT地址。");
      const headers = { ...session.headers };
      if (session.url.startsWith("/"))
        headers["X-CSRF-Token"] = (
          await api<{ token: string }>("/auth/csrf")
        ).token;
      const response = await fetch(session.url, {
        method: "PUT",
        headers,
        body: file,
        credentials: session.url.startsWith("/") ? "include" : "omit",
      });
      if (!response.ok) throw new Error(`封面上传失败（${response.status}）。`);
      await api(`/uploads/${session.id}/completion`, "POST", {});
      setUploadId(session.id);
      await cache.invalidateQueries({ queryKey: ["resource", id] });
      setSuccess("封面已提交，后台校验通过后显示。");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel" onSubmit={upload} style={{ marginTop: 24 }}>
      <h3>资源封面</h3>
      <Field label="封面图片" hint="仅用于展示，请上传有权使用的图片。">
        <input
          type="file"
          name="cover"
          accept="image/png,image/jpeg,image/webp"
          required
        />
      </Field>
      <Button disabled={busy} className="secondary">
        {busy ? "正在上传…" : "上传封面"}
      </Button>
      {error !== undefined && <Notice error={error} />}{" "}
      {success && <Notice>{success}</Notice>}
      {status.error && <Notice error={status.error} />}
      {status.data?.status === "FAILED" && (
        <Notice
          error={
            new Error(
              `封面校验失败：${status.data.errorCode ?? "请检查图片格式与大小"}`,
            )
          }
        />
      )}
      {status.data?.status === "READY" && (
        <Notice>
          封面校验完成。
          <Button
            type="button"
            className="secondary"
            onClick={() =>
              cache.invalidateQueries({ queryKey: ["resource", id] })
            }
          >
            刷新资源资料
          </Button>
        </Notice>
      )}
    </form>
  );
}
