import { clientRelease } from "@/lib/client-release";
import Link from "next/link";
import styles from "../releases.module.css";

// 正式版摘要由已核实的 GitHub 发行信息提供，不依赖资源平台接口。
export function CurrentRelease() {
  return (
    <section
      className={`panel ${styles.currentRelease}`}
      aria-labelledby="current-release-title"
    >
      <p className="eyebrow">当前正式版 · {clientRelease.publishedAt}</p>
      <h2 id="current-release-title">
        玄司 {clientRelease.version} · 先聊上第一句，遇到问题有指引。
      </h2>
      <ul>
        {clientRelease.highlights.map((highlight) => (
          <li key={highlight}>{highlight}</li>
        ))}
      </ul>
      <p className="legal-note">
        语音和形象可以稍后配置。聊天不要求网站账号，在线 AI 的调用费用由所选服务商收取。
      </p>
      <div className="actions">
        <Link className="button-link" href="/download">
          下载当前正式版
        </Link>
        <a
          className="quiet-link"
          href={clientRelease.releaseUrl}
          target="_blank"
          rel="noreferrer"
        >
          查看官方完整说明 ↗
        </a>
      </div>
    </section>
  );
}
