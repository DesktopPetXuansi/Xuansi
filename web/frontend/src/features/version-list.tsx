"use client";
import { Button, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { type Version, bytes, statuses } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
export function VersionList({
  id,
  onSelect,
}: {
  id: string;
  onSelect?: (id: string) => void;
}) {
  const query = useQuery({
    queryKey: ["versions", id],
    queryFn: () => api<Version[]>(`/resources/${id}/versions`),
    refetchInterval: (state) =>
      state.state.data?.some((version) =>
        ["PENDING", "VALIDATING"].includes(version.validationStatus),
      )
        ? 2000
        : false,
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState("");
  async function download(version: Version) {
    setBusy(version.id);
    setError(undefined);
    try {
      const data = await api<{ url: string }>(
        `/resources/${id}/versions/${version.id}/download-authorizations`,
        "POST",
        {},
      );
      window.location.assign(safeUrl(data.url));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      {query.isPending && <Notice>正在读取版本…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>尚未上传版本。</Notice>
      )}
      {query.data?.map((version) => (
        <article className="version-row" key={version.id}>
          <div className="actions">
            <h3 style={{ margin: 0 }}>{version.version}</h3>
            <span className="badge">{statuses[version.validationStatus]}</span>
            <span className="badge">
              {statuses[version.compatibilityStatus]}
            </span>
          </div>
          <p className="muted">
            最低客户端版本 {version.minimumClientVersion || "未指定"} ·{" "}
            {bytes(version.packageBytes)}
          </p>
          <code>{version.entrypoint}</code>
          <details style={{ marginTop: 12 }}>
            <summary>版本身份、校验摘要与依赖</summary>
            <p>
              <small>
                版本 ID：<code>{version.id}</code>
              </small>
            </p>
            <p>
              <small>
                SHA-256：
                <code>{version.packageSha256 || "校验完成后生成"}</code>
              </small>
            </p>
            {version.dependencies?.length ? (
              <ul>
                {version.dependencies.map((dependency) => (
                  <li key={dependency.versionId}>
                    <small>
                      {dependency.relation} ·{" "}
                      <code>{dependency.versionId}</code>
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">未声明外部模型依赖。</p>
            )}
          </details>
          {version.validationReport?.errors?.map((error, index) => (
            <Notice key={index} error={new Error(error)} />
          ))}
          {version.validationReport?.warnings?.map((warning, index) => (
            <Notice key={index}>{warning}</Notice>
          ))}
          {version.validationStatus === "READY" && (
            <div className="actions" style={{ marginTop: 16 }}>
              <Button
                onClick={() => download(version)}
                disabled={busy === version.id}
              >
                下载资源包 ↓
              </Button>
              {onSelect && (
                <Button
                  className="secondary"
                  onClick={() => onSelect(version.id)}
                >
                  设为当前版本
                </Button>
              )}
            </div>
          )}
        </article>
      ))}
      {error !== undefined && <Notice error={error} />}
    </>
  );
}
