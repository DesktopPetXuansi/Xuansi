"use client";

import { Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { clientRelease } from "@/lib/client-release";
import { type Release, bytes } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import styles from "../releases.module.css";

// 仅历史页请求平台记录，避免空库或旧记录干扰正式安装包下载。
export function PlatformHistory() {
  const query = useQuery({
    queryKey: ["releases"],
    queryFn: ({ signal }) =>
      api<Release[]>(
        "/client/releases?os=windows&arch=x64&channel=STABLE",
        "GET",
        undefined,
        false,
        { signal },
      ),
    // 历史记录失败后尽快呈现重试入口，不影响页面上方的正式版信息。
    retry: 1,
  });
  return (
    <section
      className={styles.history}
      aria-labelledby="platform-history-title"
    >
      <h2 id="platform-history-title">资源平台发布记录</h2>
      <p className="muted">
        这里是平台收录的记录，可能不包含最新正式版。当前官方下载为{" "}
        {clientRelease.version}。
      </p>
      {query.isPending && <Notice>正在读取平台记录…</Notice>}
      {query.error && (
        <div>
          <Notice error={query.error} />
          <p className="muted">
            平台记录暂时无法读取，已核实的官方下载仍可正常使用。
          </p>
          <button
            className="button secondary"
            type="button"
            disabled={query.isFetching}
            onClick={() => {
              console.info("[releases] 手动重试平台历史");
              void query.refetch();
            }}
          >
            {query.isFetching ? "正在重试…" : "重新读取平台记录"}
          </button>
        </div>
      )}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>平台暂未收录版本。可前往 GitHub 查看完整发行历史。</Notice>
      )}
      {query.data?.map((release) => (
        <article className="version-row" key={release.id}>
          <h3>
            {release.version} <span className="badge">{release.channel}</span>
          </h3>
          <p className="muted">
            {release.publishedAt
              ? new Date(release.publishedAt).toLocaleDateString("zh-CN", {
                  timeZone: "UTC",
                })
              : "未发布"}
          </p>
          <p className={styles.notes}>{release.releaseNotes}</p>
          {!!release.artifacts?.length && (
            <details className={styles.details}>
              <summary>此版本的安装文件与校验信息</summary>
              {release.artifacts.map((artifact) => (
                <div className={styles.artifact} key={artifact.id}>
                  <a
                    className="quiet-link"
                    href={safeUrl(artifact.downloadUrl)}
                  >
                    下载此版本 · {bytes(artifact.bytes)}
                  </a>
                  <p className="legal-note">
                    SHA-256：
                    <code>{artifact.sha256 || "发行方未提供摘要"}</code>
                  </p>
                  <p className="legal-note">
                    {artifact.systemRequirements?.join(" · ")}
                  </p>
                </div>
              ))}
            </details>
          )}
        </article>
      ))}
    </section>
  );
}
