import { clientRelease } from "@/lib/client-release";
import Link from "next/link";
import styles from "./home-closing.module.css";

// 正式版摘要和第二处下载入口均为静态内容，不增加首页数据请求。
export function HomeClosing() {
  return (
    <div className="container">
      <section className={styles.update} aria-labelledby="home-update-title">
        <div>
          <p className="eyebrow">
            最近一次正式更新 · {clientRelease.publishedAt}
          </p>
          <h2 id="home-update-title">
            v{clientRelease.version}，先聊上第一句。
          </h2>
          <p>
            对话页帮你检查 AI 配置，未保存的模型或密钥草稿会先提醒保存。
            先收到文字回复，再按需要设置语音和形象；遇到问题有对应的处理入口。
          </p>
        </div>
        <Link className="quiet-link" href="/changelog">
          查看完整更新记录 →
        </Link>
      </section>
      <section
        className={styles.download}
        aria-labelledby="home-download-title"
      >
        <div>
          <p className="eyebrow">从你的第一句话开始</p>
          <h2 id="home-download-title">给桌面，添一位伙伴。</h2>
          <p>Windows 10 1809 及以上 · 64 位 · 无需注册</p>
        </div>
        <div>
          <Link className="button-link" href="/download">
            下载玄司 v{clientRelease.version}
          </Link>
          <p className={styles.note}>
            先选好 AI，再开始聊天。
            <br />
            <Link href="/docs/getting-started">查看新手步骤 →</Link>
          </p>
        </div>
      </section>
    </div>
  );
}
