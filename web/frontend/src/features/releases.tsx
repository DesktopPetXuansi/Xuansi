"use client";
import { Heading, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { type Release, bytes } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
export function Releases({ history = false }: { history?: boolean }) {
  const query = useQuery({
    queryKey: ["releases"],
    queryFn: () =>
      api<Release[]>("/client/releases?os=windows&arch=x64&channel=STABLE"),
  });
  return (
    <div className="container">
      <Heading
        eyebrow="DOWNLOAD / 官方下载"
        title={
          history ? "每一次更新，都有记录。" : "先确认设备，再把玄司带回桌面。"
        }
      >
        当前已验证 Windows 11 x64，NVIDIA 显卡与 CUDA 12.4。安装需要 D
        盘，首次联网下载模型与依赖。
      </Heading>
      {!history && (
        <div className="split">
          <section className="panel">
            <p className="eyebrow">WINDOWS / 在线安装器</p>
            <h2>玄司 0.5.6</h2>
            <p>
              当前桌面客户端通过官方 GitHub Release
              分发。查看版本资产、安装说明与校验信息。
            </p>
            <a
              className="button-link"
              href="https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.5.6/Xuansi-0.5.6-windows-x64-setup.exe"
              target="_blank"
              rel="noreferrer"
            >
              下载 0.5.6 在线安装包 ↓
            </a>
            <p style={{ marginTop: 18 }}>
              <a
                className="quiet-link"
                href="https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.5.6/SHA256SUMS.txt"
                target="_blank"
                rel="noreferrer"
              >
                下载 SHA256SUMS 校验文件 ↗
              </a>
            </p>
            <p className="legal-note">
              此链接是现有项目发行来源。资源平台版本服务的发布记录另列于下方。
            </p>
          </section>
          <aside>
            <h3>安装前清单</h3>
            <ul>
              <li>Windows 11 · 64 位</li>
              <li>NVIDIA 显卡与 CUDA 12.4</li>
              <li>D 盘与足够模型存储空间</li>
              <li>首次安装可稳定联网</li>
            </ul>
            <Link className="quiet-link" href="/docs">
              阅读安装指南 ↗
            </Link>
          </aside>
        </div>
      )}
      <section style={{ marginTop: 42 }}>
        <h2>{history ? "版本记录" : "平台发布记录"}</h2>
        {query.isPending && <Notice>正在查询发布版本…</Notice>}
        {query.error && <Notice error={query.error} />}{" "}
        {!query.isPending && !query.error && !query.data?.length && (
          <Notice>平台尚未发布客户端版本记录，请使用上方官方发行入口。</Notice>
        )}
        {query.data?.map((release) => (
          <article className="version-row" key={release.id}>
            <h3>
              {release.version} <span className="badge">{release.channel}</span>
            </h3>
            <p className="muted">
              {release.publishedAt
                ? new Date(release.publishedAt).toLocaleDateString("zh-CN")
                : "未发布"}
            </p>
            <p style={{ whiteSpace: "pre-wrap" }}>{release.releaseNotes}</p>
            {release.artifacts?.map((artifact) => (
              <div key={artifact.id}>
                <a
                  className="button-link secondary"
                  href={safeUrl(artifact.downloadUrl)}
                >
                  下载安装包 · {bytes(artifact.bytes)}
                </a>
                <p>
                  <small>
                    SHA-256：
                    <code>{artifact.sha256 || "发行方未提供摘要"}</code>
                  </small>
                </p>
                <p>{artifact.systemRequirements?.join(" · ")}</p>
              </div>
            ))}
          </article>
        ))}
      </section>
    </div>
  );
}
