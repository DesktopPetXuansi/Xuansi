"use client";

import { Heading, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { clientRelease } from "@/lib/client-release";
import { type Release, bytes } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import Link from "next/link";
import styles from "./releases.module.css";

// 仅历史页请求平台记录，避免空库或旧记录干扰正式安装包下载。
function PlatformHistory() {
  const query = useQuery({
    queryKey: ["releases"],
    queryFn: () =>
      api<Release[]>("/client/releases?os=windows&arch=x64&channel=STABLE"),
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
      {query.error && <Notice error={query.error} />}
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

export function Releases({ history = false }: { history?: boolean }) {
  if (history) {
    return (
      <div className="container">
        <Heading eyebrow="更新记录" title="看看玄司有哪些变化。">
          正式安装包及完整更新说明以 GitHub 发行记录为准。
        </Heading>
        <div className="actions">
          <a
            className="button-link secondary"
            href="https://github.com/DesktopPetXuansi/Xuansi/releases"
            target="_blank"
            rel="noreferrer"
          >
            查看完整发行历史 ↗
          </a>
          <Link className="quiet-link" href="/download">
            下载当前正式版 →
          </Link>
        </div>
        <PlatformHistory />
      </div>
    );
  }
  return (
    <div className="container">
      <Heading eyebrow="下载客户端" title="把玄司带到你的桌面。">
        先安装，再选择适合你的 AI 聊天方式。下载无需注册网站账号。
      </Heading>
      <div className={styles.downloadLayout}>
        <section
          className={`panel ${styles.package}`}
          aria-labelledby="download-package-title"
        >
          <p className="eyebrow">Windows · 64 位</p>
          <h2 id="download-package-title">玄司 {clientRelease.version}</h2>
          <p className="muted">正式版 · 发布于 {clientRelease.publishedAt}</p>
          <a className="button-link" href={clientRelease.downloadUrl}>
            <Download size={18} aria-hidden />
            下载 Windows 安装包
          </a>
          <p className={styles.downloadHint}>
            在线安装器：首次安装会联网下载所选组件，请保持网络连接。
          </p>
          <div className={styles.packageLinks}>
            <a
              className="quiet-link"
              href={clientRelease.releaseUrl}
              target="_blank"
              rel="noreferrer"
            >
              下载没反应？前往 GitHub ↗
            </a>
            <Link className="quiet-link" href="/docs/getting-started">
              查看安装步骤 →
            </Link>
          </div>
          <details className={styles.details}>
            <summary>安装包校验与来源</summary>
            <p>
              安装包来自项目官方 GitHub，尚未进行代码签名。可对照发行页的
              SHA-256 文件检查下载是否完整。
            </p>
            <a
              className="quiet-link"
              href={clientRelease.checksumUrl}
              target="_blank"
              rel="noreferrer"
            >
              查看 SHA256SUMS 校验文件 ↗
            </a>
          </details>
        </section>
        <aside className={styles.requirements} aria-labelledby="device-title">
          <h2 id="device-title">你的电脑能用吗？</h2>
          <ul>
            <li>Windows 10 1809 或更新版本，64 位。</li>
            <li>安装位置和模型目录可选择，不要求 D 盘。</li>
            <li>安装向导会检查内存和存储空间，再提示可用方式。</li>
            <li>目前没有 macOS 和 Linux 安装包。</li>
          </ul>
          <Link className="quiet-link" href="/docs/troubleshooting">
            安装遇到问题 →
          </Link>
        </aside>
      </div>
      <section
        className={styles.chatSection}
        aria-labelledby="chat-choice-title"
      >
        <h2 id="chat-choice-title">选择一种 AI 聊天方式</h2>
        <p className="muted">
          桌宠形象和聊天 AI
          是两件事。聊天需要在线服务或本机模型，语音组件可以按需选择。
        </p>
        <div className={styles.chatChoices}>
          <article>
            <h3>使用在线 AI 服务</h3>
            <p>
              不要求 NVIDIA 显卡。需要联网，并填写自己从服务商获取的 API
              密钥；用量费用由服务商收取。
            </p>
            <p className="legal-note">
              对话文字会发给所选服务商；图片与长期记忆按各自的提供方式和授权处理。
            </p>
          </article>
          <article>
            <h3>使用本机 AI 模型</h3>
            <p>
              模型在自己的电脑上运行，需要额外下载文件。硬件和空间要求较高，请先按安装向导检查设备。
            </p>
            <p className="legal-note">
              标准本机方案使用 9B 模型。CPU 和实验 4B
              方案仍有限制，不保证所有电脑都能流畅运行。
            </p>
          </article>
        </div>
        <Link className="quiet-link" href="/docs/chat">
          我该怎么选、怎么设置？ →
        </Link>
      </section>
      <section className={styles.upgrade} aria-labelledby="upgrade-title">
        <div>
          <h2 id="upgrade-title">已经装过玄司？</h2>
          <p>
            先从托盘退出桌宠，再运行新版安装包并选择原安装目录。记忆、人设和导入形象会保留；模型及语音设置按本次向导更新，旧设置会另行备份。
          </p>
        </div>
        <Link className="quiet-link" href="/changelog">
          查看更新记录 →
        </Link>
      </section>
    </div>
  );
}
