"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useMe } from "@/components/navigation";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { kinds, type Resource } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CoverUpload } from "./cover-upload";
import { ResourceDetailsForm } from "./resource-details-form";
import {
  ResourceUploadGuide,
  ResourceUploadSteps,
} from "./resource-upload-guide";
import styles from "./resource-upload.module.css";
import { VersionList } from "./resources";
import { UploadVersion } from "./upload-version";

export function ResourceEditor({ id }: { id?: string }) {
  const me = useMe();
  const resource = useQuery({
    queryKey: ["resource", id],
    queryFn: () => api<Resource>(`/resources/${id}`),
    enabled: !!id,
  });
  const router = useRouter();
  const cache = useQueryClient();
  const [kind, setKind] = useState("MODEL");
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  async function change(body: unknown) {
    setError(undefined);
    setSuccess("");
    try {
      await api(`/resources/${id}`, "PATCH", body);
      await cache.invalidateQueries({ queryKey: ["resource", id] });
      setSuccess("作品已更新。");
      console.debug("[作品上传] 作品状态已更新");
    } catch (cause) {
      setError(cause);
      console.warn("[作品上传] 作品状态更新失败");
    }
  }

  async function remove() {
    if (busy) return;
    setBusy(true);
    setError(undefined);
    try {
      await api(`/resources/${id}`, "DELETE");
      setDeleteOpen(false);
      router.push("/dashboard/resources");
      console.debug("[作品上传] 作品已删除");
    } catch (cause) {
      setError(cause);
      console.warn("[作品上传] 删除作品失败");
    } finally {
      setBusy(false);
    }
  }

  if (id && resource.isPending) return <Notice>正在读取作品…</Notice>;
  if (resource.error) return <Notice error={resource.error} />;
  const item = resource.data;
  const verified = !!me.data?.emailVerified;
  return (
    <>
      <Heading eyebrow="创作者工作台" title={item ? item.name : "上传你的作品"}>
        {item
          ? item.visibility === "PRIVATE"
            ? "上传后先检查校验结果，再选择当前版本。作品目前私有，公开需要管理员操作。"
            : "上传后先检查校验结果，再选择当前版本。作品的公开状态由管理员管理。"
          : "先填写资料，再选择文件上传。作品默认私有，公开需要管理员操作。"}
      </Heading>
      <ResourceUploadSteps current={item ? 2 : 1} />
      {!verified && (
        <Notice>
          上传作品前请先验证邮箱。
          <Link className="quiet-link" href="/verify-email">
            前往验证邮箱
          </Link>
        </Notice>
      )}
      {!item ? (
        <>
          <div className={styles.typePicker}>
            <Field label="你要上传什么？">
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger aria-label="你要上传什么？" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent position="popper">
                  {Object.entries(kinds).map(([value, label]) => (
                    <SelectItem value={value} key={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <ResourceUploadGuide kind={kind} />
          <ResourceDetailsForm
            verified={verified}
            kind={kind}
            onCreated={(saved) =>
              router.push(`/dashboard/resources/${saved.id}#upload-version`)
            }
          />
        </>
      ) : (
        <>
          {item.status === "DISABLED" && (
            <Notice>作品已被管理员停用，恢复后才能上传和使用。</Notice>
          )}
          <section
            className={styles.section}
            id="upload-version"
            aria-labelledby="upload-version-title"
          >
            <h2 id="upload-version-title">
              上传{item.kind === "MODEL" ? "模型" : "作品"}文件
            </h2>
            <p>
              {item.kind === "MODEL"
                ? "选择包含 Live2D 运行文件的 .zip 压缩包。"
                : "选择要供下载和使用的文件。"}
              封面可以稍后单独上传。
            </p>
            <ResourceUploadGuide kind={item.kind} compact />
            {item.status === "DISABLED" ? (
              <Notice>请联系管理员处理作品停用状态。</Notice>
            ) : verified ? (
              <UploadVersion resource={item} />
            ) : null}
          </section>
          <section className={styles.section} aria-labelledby="versions-title">
            <h2 id="versions-title">已上传版本</h2>
            <p>
              校验完成后，选择“设为当前版本”。校验通过还需要在客户端试用确认效果。
            </p>
            <VersionList
              id={item.id}
              currentVersionId={item.currentVersionId}
              onSelect={(versionId) =>
                void change({ currentVersionId: versionId })
              }
            />
          </section>
          {error !== undefined && <Notice error={error} />}
          {success && <Notice>{success}</Notice>}
          <Collapsible className={styles.settings}>
            <CollapsibleTrigger>
              修改作品资料、封面和管理作品
            </CollapsibleTrigger>
            <CollapsibleContent
              forceMount
              className="data-[state=closed]:hidden"
            >
              <ResourceDetailsForm
                item={item}
                verified={verified}
                kind={item.kind}
                onCreated={() => {}}
              />
              {item.status !== "DISABLED" && verified && (
                <CoverUpload id={item.id} />
              )}
              <div className="actions">
                {item.status !== "DISABLED" && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      void change({
                        status: item.status === "HIDDEN" ? "ACTIVE" : "HIDDEN",
                      })
                    }
                  >
                    {item.status === "HIDDEN" ? "恢复作品" : "隐藏作品"}
                  </Button>
                )}
                <AlertDialog
                  open={deleteOpen}
                  onOpenChange={(open) => {
                    if (busy) return;
                    if (open) setError(undefined);
                    setDeleteOpen(open);
                    console.debug(
                      "[作品上传]",
                      open ? "打开删除确认" : "关闭删除确认",
                    );
                  }}
                >
                  <AlertDialogTrigger asChild>
                    <Button variant="destructive" disabled={busy}>
                      删除作品
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent
                    onEscapeKeyDown={(event) => {
                      if (busy) event.preventDefault();
                    }}
                  >
                    <AlertDialogHeader>
                      <AlertDialogTitle>删除这个资源？</AlertDialogTitle>
                      <AlertDialogDescription>
                        删除后无法恢复。已被引用的资源不能删除。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    {error !== undefined && <Notice error={error} />}
                    <AlertDialogFooter>
                      <AlertDialogCancel disabled={busy}>
                        取消
                      </AlertDialogCancel>
                      <AlertDialogAction
                        variant="destructive"
                        disabled={busy}
                        onClick={(event) => {
                          // 异步删除结束后再关闭确认，失败时保留说明和重试入口。
                          event.preventDefault();
                          void remove();
                        }}
                      >
                        {busy ? "正在删除…" : "确认删除"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </>
      )}
    </>
  );
}
