"use client";

import { Heading } from "@/components/ui";
import { clientRelease } from "@/lib/client-release";
import { bytes } from "@/lib/types";
import { Download } from "lucide-react";
import Link from "next/link";
import styles from "./releases.module.css";
import { PackageChecksum } from "./releases/checksum";
import { CurrentRelease } from "./releases/current-release";
import { PlatformHistory } from "./releases/platform-history";
import { AiModes } from "./ai-modes";

export function Releases({ history = false }: { history?: boolean }) {
  if (history) {
    return (
      <div className="container">
        <Heading eyebrow="更新记录" title="看看玄司有哪些变化。">
          正式安装包及完整更新说明以 GitHub 发行记录为准。
        </Heading>
        <CurrentRelease />
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
          <dl className={styles.packageFacts}>
            <div>
              <dt>安装文件</dt>
              <dd>{bytes(clientRelease.bytes)} · 在线安装器</dd>
            </div>
            <div>
              <dt>账号要求</dt>
              <dd>下载和客户端基础使用无需注册</dd>
            </div>
            <div>
              <dt>代码签名</dt>
              <dd>
                {clientRelease.signing === "unsigned"
                  ? "尚未进行代码签名"
                  : "已签名"}
              </dd>
            </div>
          </dl>
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
          <PackageChecksum />
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
      <AiModes />
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
