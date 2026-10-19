"use client";
import { Button, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { type Version, bytes, statuses } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import styles from "./resources.module.css";

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
      console.debug("[资源下载] 已取得下载授权");
    } catch (cause) {
      setError(cause);
      console.warn("[资源下载] 下载授权失败，请查看页面提示");
    } finally {
      setBusy("");
    }
  }
  // 保留接口顺序，不把没有发布时间证明的版本称作最新版；不兼容项不推荐。
  const available = query.data?.find(
    (version) =>
      version.validationStatus === "READY" &&
      version.compatibilityStatus !== "INCOMPATIBLE",
  );
  const otherVersions = query.data?.filter(
    (version) => version.id !== available?.id,
  );
  function versionRow(version: Version) {
    return (
      <article
        className="version-row"
        key={version.id}
        id={`version-${version.id}`}
      >
        <div className="actions">
          <h3 style={{ margin: 0 }}>
            {!onSelect && version.id === available?.id
              ? `可下载版本 ${version.version}`
              : `版本 ${version.version}`}
          </h3>
          <span className="badge">{statuses[version.validationStatus]}</span>
          <span className="badge">{statuses[version.compatibilityStatus]}</span>
        </div>
        <p className="muted">
          {bytes(version.packageBytes)}
          {version.minimumClientVersion
            ? ` · 需要客户端 ${version.minimumClientVersion} 或更新版本`
            : " · 作者未指定最低客户端版本"}
        </p>
        {version.compatibilityStatus === "INCOMPATIBLE" && (
          <Notice>
            此版本标记为不兼容。请先联系作者或选择其他版本；下载文件不代表可以正常使用。
          </Notice>
        )}
        {version.validationStatus === "READY" &&
          version.compatibilityStatus === "UNTESTED" && (
            <p className="muted">
              文件校验已完成，是否能正常显示仍需在客户端预览确认。
            </p>
          )}
        <details className={styles.versionDetails}>
          <summary>文件信息、校验与配套依赖</summary>
          <p>
            入口文件：<code>{version.entrypoint || "未指定"}</code>
          </p>
          <p>
            版本 ID：<code>{version.id}</code>
          </p>
          <p>
            SHA-256：<code>{version.packageSha256 || "校验完成后生成"}</code>
          </p>
          {version.dependencies?.length ? (
            <ul>
              {version.dependencies.map((dependency) => (
                <li key={dependency.versionId}>
                  {dependency.relation} · <code>{dependency.versionId}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">作者未声明外部模型依赖。</p>
          )}
        </details>
        {version.dependencies?.length ? (
          <p>此资源需要配套模型，请展开文件信息核对依赖版本。</p>
        ) : null}
        {version.validationReport?.errors?.map((message, index) => (
          <Notice key={index} error={new Error(message)} />
        ))}
        {version.validationReport?.warnings?.map((warning, index) => (
          <Notice key={index}>{warning}</Notice>
        ))}
        {version.validationStatus === "READY" && (
          <div className="actions" style={{ marginTop: 16 }}>
            <Button
              onClick={() => void download(version)}
              disabled={busy !== ""}
            >
              {busy === version.id
                ? "正在准备下载…"
                : version.compatibilityStatus === "INCOMPATIBLE"
                  ? "仍要下载文件 ↓"
                  : "下载资源包 ↓"}
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
    );
  }
  return (
    <>
      {query.isPending && <Notice>正在读取可下载版本…</Notice>}
      {query.error && <Notice error={query.error} />}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>作者还没有上传可用版本，请稍后再来。</Notice>
      )}
      {onSelect ? (
        query.data?.map(versionRow)
      ) : (
        <>
          {available && versionRow(available)}
          {!!otherVersions?.length && (
            <details className={styles.versionDetails} open={!available}>
              <summary>
                {available
                  ? "查看其他版本与校验状态"
                  : "目前没有可推荐的版本，查看校验状态"}
              </summary>
              {otherVersions.map(versionRow)}
            </details>
          )}
        </>
      )}
      {error !== undefined && <Notice error={error} />}
    </>
  );
}
