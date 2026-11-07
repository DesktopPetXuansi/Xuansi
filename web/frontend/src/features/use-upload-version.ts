"use client";

import { api, message } from "@/lib/api";
import type { Resource, Upload, Version } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { putFile } from "./upload-file";

export function useUploadVersion(resource: Resource) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<"preparing" | "uploading" | "confirming">(
    "preparing",
  );
  const [error, setError] = useState<unknown>();
  const [file, setFile] = useState<File>();
  const [upload, setUpload] = useState<Upload>();
  const [pendingCompletion, setPendingCompletion] = useState<{
    upload: Upload;
    key: string;
  }>();
  const submitting = useRef(false);
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    const form = new FormData(event.currentTarget);
    const selected = form.get("file");
    if (!(selected instanceof File) || !selected.size) {
      setError(new Error("请选择非空的作品文件。"));
      return;
    }
    if (resource.kind === "MODEL" && !selected.name.endsWith(".zip")) {
      setError(
        new Error(
          "请选择文件名以 .zip 结尾的 Live2D 运行文件压缩包；.cmo3 工程需要先导出。",
        ),
      );
      return;
    }
    const targetModelVersionId = form.get("targetModelVersionId");
    const entrypoint = form.get("entrypoint");
    let createdUpload: Upload | undefined;
    let fileSent = false;
    // 上传和创建版本不能因连续点击重复执行。
    submitting.current = true;
    setBusy(true);
    setError(undefined);
    setProgress(0);
    setPhase("preparing");
    setUpload(undefined);
    setPendingCompletion(undefined);
    try {
      const created = await api<{ version: Version; upload: Upload }>(
        `/resources/${resource.id}/versions`,
        "POST",
        {
          version: String(form.get("version")).trim(),
          filename: selected.name,
          expectedBytes: selected.size,
          minimumClientVersion: String(form.get("minimumClientVersion")).trim(),
          targetModelVersionId:
            typeof targetModelVersionId === "string" &&
            targetModelVersionId.trim()
              ? targetModelVersionId.trim()
              : undefined,
          entrypoint:
            typeof entrypoint === "string" && entrypoint.trim()
              ? entrypoint.trim()
              : undefined,
        },
      );
      createdUpload = created.upload;
      // 保存任务身份后，即使传输或确认失败，也能查看真实状态。
      setUpload(created.upload);
      if (created.upload.method !== "PUT")
        throw new Error("当前上传服务未提供受支持的上传地址，请联系管理员。");
      setPhase("uploading");
      await putFile(created.upload, selected, setProgress);
      fileSent = true;
      setPhase("confirming");
      const key = crypto.randomUUID();
      setPendingCompletion({ upload: created.upload, key });
      const completed = await api<Upload>(
        `/uploads/${created.upload.id}/completion`,
        "POST",
        {},
        false,
        { idempotencyKey: key },
      );
      setUpload(completed);
      cache.setQueryData(["upload", completed.id], completed);
      setPendingCompletion(undefined);
      await cache.invalidateQueries({ queryKey: ["versions", resource.id] });
      console.debug("[作品上传] 文件已提交后台校验");
    } catch (cause) {
      setError(
        fileSent
          ? new Error(`${message(cause)} 文件已发送，可以重试提交校验。`)
          : createdUpload
            ? new Error(
                `${message(cause)} 上传任务已创建，请查看上传队列；如需重新上传，请使用新的版本号。`,
              )
            : cause,
      );
      // 创建版本的结果也可能因网络中断而未知，列表用于找回已创建的记录。
      await cache.invalidateQueries({ queryKey: ["versions", resource.id] });
      console.warn("[作品上传] 上传未完成，请查看页面状态");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  async function retryCompletion() {
    if (!pendingCompletion || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setPhase("confirming");
    setError(undefined);
    try {
      // 同一个上传任务和幂等编号只重新提交校验，不创建版本或重传文件。
      const completed = await api<Upload>(
        `/uploads/${pendingCompletion.upload.id}/completion`,
        "POST",
        {},
        false,
        { idempotencyKey: pendingCompletion.key },
      );
      setUpload(completed);
      cache.setQueryData(["upload", completed.id], completed);
      setPendingCompletion(undefined);
      await cache.invalidateQueries({ queryKey: ["versions", resource.id] });
      console.debug("[作品上传] 已重新提交后台校验");
    } catch (cause) {
      setError(new Error(`${message(cause)} 校验提交尚未确认，可以再次重试。`));
      console.warn("[作品上传] 提交校验未确认");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  // 完成请求响应丢失后，服务端已进入校验或终态时应以真实状态为准。
  const confirmed =
    !!upload &&
    !!state.data &&
    ["VALIDATING", "READY", "FAILED", "CANCELLED", "EXPIRED"].includes(
      state.data.status,
    );
  const visibleError = confirmed ? undefined : error;
  const canRetryCompletion =
    !!pendingCompletion &&
    !confirmed &&
    !["CANCELLED", "EXPIRED"].includes(state.data?.status ?? "");
  function selectFile(selected?: File) {
    setFile(selected);
    setUpload(undefined);
    setPendingCompletion(undefined);
    setError(undefined);
    console.debug("[作品上传] 已选择文件");
  }

  return {
    busy,
    progress,
    phase,
    file,
    upload,
    visibleError,
    canRetryCompletion,
    status: state.data?.status,
    statusError: state.error,
    selectFile,
    submit,
    retryCompletion,
  };
}
