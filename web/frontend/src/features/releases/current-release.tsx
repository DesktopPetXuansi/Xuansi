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
        玄司 {clientRelease.version} · 选中形象，直接使用。
      </h2>
      <ul>
        {clientRelease.highlights.map((highlight) => (
          <li key={highlight}>{highlight}</li>
        ))}
      </ul>
      <p className="legal-note">
        形象历史同步还需要用户主动开启、独立授权及网站支持。客户端更新不代表服务器已更新。
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
