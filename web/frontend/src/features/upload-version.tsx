"use client";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Resource, type Upload, type Version } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function UploadVersion({ resource }: { resource: Resource }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<unknown>();
  const [upload, setUpload] = useState<Upload>();
  const cache = useQueryClient();
  const state = useQuery({
    queryKey: ["upload", upload?.id],
    queryFn: () => api<Upload>(`/uploads/${upload?.id}`),
    enabled: !!upload,
    refetchInterval: (query) =>
      query.state.data &&
      ["READY", "FAILED", "CANCELLED", "EXPIRED"].includes(
        query.state.data.status,
      )
        ? false
        : 2000,
  });
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || !file.size) return;
    // 不存在的可选输入必须省略，不能把 FormData 的 null 变成字符串。
    const targetModelVersionId = form.get("targetModelVersionId");
    setBusy(true);
    setError(undefined);
    setProgress(0);
    try {
      const created = await api<{ version: Version; upload: Upload }>(
        `/resources/${resource.id}/versions`,
        "POST",
        {
          version: String(form.get("version")),
          filename: file.name,
          expectedBytes: file.size,
          minimumClientVersion: String(form.get("minimumClientVersion")),
          targetModelVersionId:
            typeof targetModelVersionId === "string" && targetModelVersionId
              ? targetModelVersionId
              : undefined,
          entrypoint: String(form.get("entrypoint")) || undefined,
        },
      );
      if (created.upload.method !== "PUT")
        throw new Error("当前上传服务未提供受支持的 PUT 地址，请联系管理员。");
      await putFile(created.upload, file, setProgress);
      await api(`/uploads/${created.upload.id}/completion`, "POST", {});
      setUpload(created.upload);
      await cache.invalidateQueries({ queryKey: ["versions", resource.id] });
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel" onSubmit={submit}>
      <p className="muted">
        Live2D 模型上传
        ZIP，完整保留导出文件相对路径。动作和表情绑定精确的模型版本，上传不等于客户端兼容。
      </p>
      <div className="grid-two">
        <Field label="版本号">
          <input name="version" placeholder="1.0.0" required />
        </Field>
        <Field label="最低客户端版本">
          <input
            name="minimumClientVersion"
            placeholder="接入版实际最低版本；未验证可留空"
          />
        </Field>
      </div>
      <Field
        label="模型入口路径"
        hint="模型 ZIP 内的 .model3.json 相对路径；其他类型可留空。"
      >
        <input
          name="entrypoint"
          placeholder="character/character.model3.json"
        />
      </Field>
      {["MOTION", "EXPRESSION"].includes(resource.kind) && (
        <Field label="目标模型版本 ID">
          <input
            name="targetModelVersionId"
            required
            placeholder="精确模型版本 UUID"
          />
        </Field>
      )}
      <Field label="资源文件">
        <input
          name="file"
          type="file"
          required
          accept={
            resource.kind === "MODEL"
              ? ".zip"
              : resource.kind === "MOTION"
                ? ".motion3.json"
                : resource.kind === "EXPRESSION"
                  ? ".exp3.json"
                  : resource.kind === "IMAGE"
                    ? "image/png,image/jpeg,image/webp"
                    : ".gif"
          }
        />
      </Field>
      <Button disabled={busy}>{busy ? "正在上传…" : "上传并校验"}</Button>
      {busy && (
        <>
          <p role="status">已上传 {progress}%</p>
          <progress className="progress" max={100} value={progress} />
        </>
      )}
      {error !== undefined && <Notice error={error} />}{" "}
      {state.error && <Notice error={state.error} />}{" "}
      {state.data && (
        <Notice>
          {state.data.status === "READY"
            ? "文件校验完成，请在版本列表检查兼容性并选择当前版本。"
            : state.data.status === "FAILED"
              ? `校验失败：${state.data.errorCode ?? "请查看版本报告"}`
              : "文件已提交，正在后台校验。"}
        </Notice>
      )}
    </form>
  );
}
// XHR仅用于文件字节进度；业务状态始终以服务端校验结果为准。
async function putFile(
  upload: Upload,
  file: File,
  onProgress: (value: number) => void,
) {
  let csrf: string | undefined;
  if (upload.url.startsWith("/"))
    csrf = (await api<{ token: string }>("/auth/csrf")).token;
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", upload.url);
    xhr.withCredentials = upload.url.startsWith("/");
    Object.entries(upload.headers ?? {}).forEach(([key, value]) =>
      xhr.setRequestHeader(key, value),
    );
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`文件上传失败（${xhr.status}），请重试。`));
    xhr.onerror = () => reject(new Error("文件上传连接中断，请重试。"));
    xhr.send(file);
  });
}
