"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";

import { Button, Field, Notice } from "@/components/ui";
import { bytes, type Resource, type Upload } from "@/lib/types";
import Link from "next/link";
import { useUploadVersion } from "./use-upload-version";
import styles from "./resource-upload.module.css";

export function UploadVersion({ resource }: { resource: Resource }) {
  const {
    busy,
    progress,
    phase,
    file,
    upload,
    visibleError,
    canRetryCompletion,
    status,
    statusError,
    selectFile,
    submit,
    retryCompletion,
  } = useUploadVersion(resource);
  const accept =
    resource.kind === "MODEL"
      ? ".zip"
      : resource.kind === "MOTION"
        ? ".motion3.json"
        : resource.kind === "EXPRESSION"
          ? ".exp3.json"
          : resource.kind === "IMAGE"
            ? "image/png,image/jpeg,image/webp"
            : ".gif";
  return (
    <form className="panel" onSubmit={submit}>
      <Field
        label={resource.kind === "MODEL" ? "选择模型压缩包" : "选择作品文件"}
      >
        <Input
          name="file"
          type="file"
          required
          accept={accept}
          disabled={busy}
          onChange={(event) => selectFile(event.target.files?.[0])}
        />
      </Field>
      {file && (
        <p className={styles.fileSummary} role="status">
          已选择：{file.name}（{bytes(file.size)}）
        </p>
      )}
      <Field
        label="版本号"
        hint="第一次上传可以填写 1.0.0；再次上传请使用新的版本号。"
      >
        <Input
          name="version"
          placeholder="例如 1.0.0"
          required
          disabled={busy}
        />
      </Field>
      {["MOTION", "EXPRESSION"].includes(resource.kind) && (
        <Field
          label="配套模型版本 ID"
          hint="在对应模型的版本列表展开“文件信息”，复制版本 ID。"
        >
          <Input
            name="targetModelVersionId"
            required
            placeholder="粘贴模型版本 ID"
            disabled={busy}
          />
        </Field>
      )}
      <Collapsible className={styles.advanced}>
        <CollapsibleTrigger>高级设置（选填）</CollapsibleTrigger>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <Field
            label="最低客户端版本"
            hint="已确认最低支持版本时填写，例如 0.9.0；不确定可留空。"
          >
            <Input
              name="minimumClientVersion"
              placeholder="例如 0.9.0"
              disabled={busy}
            />
          </Field>
          {resource.kind === "MODEL" && (
            <Field
              label="模型入口路径"
              hint="只有压缩包包含多个 .model3.json 时才需填写：输入入口文件在 ZIP 内的相对路径。"
            >
              <Input
                name="entrypoint"
                placeholder="角色文件夹/角色.model3.json"
                disabled={busy}
              />
            </Field>
          )}
        </CollapsibleContent>
      </Collapsible>
      <p>文件会先进行后台校验；校验完成不代表已公开。</p>
      <Button type="submit" disabled={busy || canRetryCompletion}>
        {busy ? "正在上传…" : "上传文件并校验"}
      </Button>
      {busy && (
        <>
          <p role="status">
            {phase === "preparing"
              ? "正在准备上传任务…"
              : phase === "confirming" || progress === 100
                ? "文件已发送，正在等待服务器确认…"
                : `文件上传中：${progress}%`}
          </p>
          {phase !== "preparing" && (
            <Progress value={progress} aria-label="文件上传进度" />
          )}
        </>
      )}
      {visibleError !== undefined && <Notice error={visibleError} />}
      {canRetryCompletion && visibleError !== undefined && (
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void retryCompletion()}
        >
          重试提交校验
        </Button>
      )}
      {visibleError !== undefined && upload && (
        <Link href="/dashboard/uploads" className="quiet-link">
          查看上传队列
        </Link>
      )}
      {statusError && <Notice error={statusError} />}
      {!busy && status && (
        <UploadStatus status={status} canRetry={canRetryCompletion} />
      )}
    </form>
  );
}

function UploadStatus({
  status,
  canRetry,
}: {
  status: Upload["status"];
  canRetry: boolean;
}) {
  if (status === "READY")
    return (
      <Notice>
        文件校验已完成。请在下方“已上传版本”选择当前版本；上传不会改变作品的公开状态。
      </Notice>
    );
  if (status === "FAILED")
    return (
      <Notice
        error={
          new Error(
            "文件校验未通过，请查看下方版本列表中的具体原因；修正后使用新的版本号重新上传。",
          )
        }
      />
    );
  if (status === "CANCELLED")
    return <Notice>上传已取消。如需重新上传，请使用新的版本号。</Notice>;
  if (status === "EXPIRED")
    return <Notice>上传任务已过期。如需重新上传，请使用新的版本号。</Notice>;
  if (status === "CREATED")
    return (
      <Notice>
        {canRetry
          ? "文件已发送，等待提交后台校验。"
          : "上传任务已创建，文件尚未确认上传。请查看上传队列。"}
      </Notice>
    );
  if (status === "UPLOADED")
    return (
      <Notice>
        {canRetry
          ? "文件已上传，可以重试提交后台校验。"
          : "文件已上传，等待提交后台校验。请查看上传队列。"}
      </Notice>
    );
  return <Notice>文件已提交，正在后台校验；请稍候查看下方版本列表。</Notice>;
}
