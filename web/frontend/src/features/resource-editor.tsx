"use client";
import { useMe } from "@/components/navigation";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Resource, kinds } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CoverUpload } from "./cover-upload";
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
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    const values = new FormData(event.currentTarget);
    const body = {
      name: String(values.get("name")),
      description: String(values.get("description")),
      author: String(values.get("author")),
      license: String(values.get("license")),
      source: String(values.get("source")),
      tags: String(values.get("tags"))
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    };
    try {
      const saved = await api<Resource>(
        id ? `/resources/${id}` : "/resources",
        id ? "PATCH" : "POST",
        id ? body : { ...body, kind: String(values.get("kind")) },
      );
      await cache.invalidateQueries({ queryKey: ["resource", id] });
      setSuccess("资源资料已保存。");
      if (!id) router.push(`/dashboard/resources/${saved.id}`);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function change(body: unknown) {
    setError(undefined);
    try {
      await api(`/resources/${id}`, "PATCH", body);
      await cache.invalidateQueries({ queryKey: ["resource", id] });
      setSuccess("资源已更新。");
    } catch (cause) {
      setError(cause);
    }
  }
  async function remove() {
    if (!window.confirm("删除这个资源？已被引用的资源不能删除。")) return;
    setBusy(true);
    try {
      await api(`/resources/${id}`, "DELETE");
      router.push("/dashboard/resources");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  if (id && resource.isPending) return <Notice>正在读取资源…</Notice>;
  if (resource.error) return <Notice error={resource.error} />;
  const item = resource.data;
  return (
    <>
      <Heading
        eyebrow="CREATOR / 资源管理"
        title={id ? "编辑资源" : "创建你的第一个版本"}
      >
        先记录资源身份和许可，再上传文件。新资源默认私有。
      </Heading>
      <form onSubmit={save} className="panel" key={item?.id ?? "new"}>
        <div className="grid-two">
          <Field label="资源名称">
            <input
              name="name"
              required
              maxLength={120}
              defaultValue={item?.name}
            />
          </Field>
          <Field label="资源类型">
            <select
              name="kind"
              defaultValue={item?.kind ?? "MODEL"}
              disabled={!!id}
            >
              {Object.entries(kinds).map(([kind, label]) => (
                <option value={kind} key={kind}>
                  {label}
                </option>
              ))}
            </select>
            {id && <input name="kind" type="hidden" value={item?.kind} />}
          </Field>
        </div>
        <Field label="介绍">
          <textarea name="description" defaultValue={item?.description} />
        </Field>
        <div className="grid-two">
          <Field label="作者">
            <input name="author" required defaultValue={item?.author} />
          </Field>
          <Field label="使用许可" hint="明确允许的用途和再分发条件。">
            <input
              name="license"
              required
              defaultValue={item?.license}
              placeholder="例如：仅个人使用，禁止再分发"
            />
          </Field>
        </div>
        <Field label="来源链接">
          <input type="url" name="source" defaultValue={item?.source} />
        </Field>
        <Field label="标签" hint="用英文逗号分隔。">
          <input name="tags" defaultValue={item?.tags.join(", ")} />
        </Field>
        <Button disabled={busy}>{busy ? "正在保存…" : "保存资料"}</Button>
      </form>
      {error !== undefined && <Notice error={error} />}{" "}
      {success && <Notice>{success}</Notice>}
      {id && item && (
        <>
          {item.status === "DISABLED" && (
            <Notice>资源已被管理员停用，恢复后才能上传和使用。</Notice>
          )}
          {item.status !== "DISABLED" && <CoverUpload id={id} />}
          <section style={{ marginTop: 40 }}>
            <h2>上传新版本</h2>
            {item.status === "DISABLED" ? (
              <Notice>请联系管理员处理资源停用状态。</Notice>
            ) : me.data?.emailVerified ? (
              <UploadVersion resource={item} />
            ) : (
              <Notice>
                请先验证邮箱，再上传文件。
                <a className="quiet-link" href="/verify-email">
                  发送验证邮件
                </a>
              </Notice>
            )}
          </section>
          <section style={{ marginTop: 40 }}>
            <h2>已有版本</h2>
            <VersionList
              id={id}
              onSelect={(versionId) => change({ currentVersionId: versionId })}
            />
          </section>
          <section className="actions" style={{ marginTop: 30 }}>
            {item.status !== "DISABLED" && <Button
              className="secondary"
              onClick={() =>
                change({
                  status: item.status === "HIDDEN" ? "ACTIVE" : "HIDDEN",
                })
              }
            >
              {item.status === "HIDDEN" ? "恢复资源" : "隐藏资源"}
            </Button>}
            <Button className="danger" disabled={busy} onClick={remove}>
              删除资源
            </Button>
          </section>
        </>
      )}
    </>
  );
}
