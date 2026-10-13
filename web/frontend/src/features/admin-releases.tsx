"use client";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Release } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function ReleaseAdmin() {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-releases"],
    queryFn: () => api<Release[]>("/admin/client-releases"),
  });
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Release>();
  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    const form = new FormData(event.currentTarget);
    try {
      await api(
        editing
          ? `/admin/client-releases/${editing.id}`
          : "/admin/client-releases",
        editing ? "PATCH" : "POST",
        editing ? { releaseNotes: String(form.get("releaseNotes")) } : {
          version: String(form.get("version")),
          channel: String(form.get("channel")),
          sourceCommit: String(form.get("sourceCommit")),
          releaseNotes: String(form.get("releaseNotes")),
          artifacts: [
            {
              os: "windows",
              arch: "x64",
              distributionType: "ONLINE_INSTALLER",
              downloadUrl: String(form.get("downloadUrl")),
              sha256: String(form.get("sha256")),
              bytes: Number(form.get("bytes")),
              systemRequirements: [
                "Windows 11 x64",
                "NVIDIA / CUDA 12.4",
                "D 盘",
                "首次联网",
              ],
            },
          ],
        },
      );
      await cache.invalidateQueries({ queryKey: ["admin-releases"] });
      setSuccess(editing ? "版本说明已保存。" : "版本草稿已创建，请核对后发布。");
      setEditing(undefined);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function publish(id: string) {
    setBusy(true);
    try {
      await api(`/admin/client-releases/${id}/publications`, "POST", {});
      await cache.invalidateQueries({ queryKey: ["admin-releases"] });
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <form className="panel" onSubmit={create} key={editing?.id ?? "new"}>
        <h2>{editing ? "编辑版本草稿" : "创建版本草稿"}</h2>
        {editing && <p className="muted">草稿的版本身份与安装包保持固定，此处可修改更新说明。</p>}
        <div className="grid-two">
          <Field label="版本">
            <input
              name="version"
              disabled={!!editing}
              required
              placeholder="0.5.6"
              defaultValue={editing?.version}
            />
          </Field>
          <Field label="渠道">
            <select name="channel" disabled={!!editing} defaultValue={editing?.channel}>
              <option>STABLE</option>
              <option>BETA</option>
            </select>
          </Field>
        </div>
        <Field label="源码提交">
          <input
            name="sourceCommit"
            disabled={!!editing}
            required
            defaultValue={editing?.sourceCommit}
          />
        </Field>
        <Field label="更新说明">
          <textarea
            name="releaseNotes"
            required
            defaultValue={editing?.releaseNotes}
          />
        </Field>
        <Field label="安装包 URL">
          <input
            name="downloadUrl"
            disabled={!!editing}
            type="url"
            required
            defaultValue={editing?.artifacts[0]?.downloadUrl}
          />
        </Field>
        <div className="grid-two">
          <Field label="SHA-256">
            <input
              name="sha256"
              disabled={!!editing}
              pattern="[a-fA-F0-9]{64}"
              required
              defaultValue={editing?.artifacts[0]?.sha256}
            />
          </Field>
          <Field label="字节数">
            <input
              name="bytes"
              disabled={!!editing}
              type="number"
              min={1}
              required
              defaultValue={editing?.artifacts[0]?.bytes}
            />
          </Field>
        </div>
        <Button disabled={busy}>保存草稿</Button>
        {editing && (
          <Button
            className="secondary"
            type="button"
            onClick={() => setEditing(undefined)}
          >
            取消编辑
          </Button>
        )}
      </form>
      {error !== undefined && <Notice error={error} />}{" "}
      {success && <Notice>{success}</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {query.data?.map((release) => (
        <article className="version-row" key={release.id}>
          <h3>
            {release.version} · {release.channel}
          </h3>
          <p style={{ whiteSpace: "pre-wrap" }}>{release.releaseNotes}</p>
          {release.publishedAt ? (
            <p>发布于 {release.publishedAt}</p>
          ) : (
            <div className="actions">
              <Button disabled={busy} onClick={() => publish(release.id)}>
                确认发布
              </Button>
              <Button className="secondary" onClick={() => setEditing(release)}>
                编辑草稿
              </Button>
            </div>
          )}
        </article>
      ))}
    </>
  );
}
