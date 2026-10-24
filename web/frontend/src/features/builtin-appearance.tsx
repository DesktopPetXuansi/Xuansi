import Image from "next/image";
import Link from "next/link";
import styles from "./resources.module.css";

// 自带形象是产品的真实内容，不伪装成社区发布或新增可下载资源。
export function BuiltinAppearance() {
  return (
    <section className={styles.builtin} aria-labelledby="builtin-appearance">
      <div className={styles.builtinStage}>
        <span className={styles.stageLabel}>XUANSI / 玄司</span>
        <Image
          src="/brand/front.png"
          alt="客户端自带的玄司形象"
          width={1024}
          height={1536}
          sizes="(max-width: 640px) 210px, 300px"
          priority
        />
        <span className={styles.stageCaption}>自带形象 · 安装后即可使用</span>
      </div>
      <div className={styles.builtinCopy}>
        <span className={styles.builtinLabel}>从玄司开始</span>
        <h2 id="builtin-appearance">玄司</h2>
        <p className={styles.builtinDescription}>
          黑衣金纹的国风桌面伙伴。形象已随客户端提供，装好就能和他见面。
        </p>
        <p className={styles.builtinNote}>
          也可以换成你喜欢的图片、动图或 Live2D 外观。换形象不需要先上传到网站。
        </p>
        <div className="actions">
          <Link className="button-link" href="/download">
            下载客户端
          </Link>
          <Link className="quiet-link" href="/docs/appearance">
            查看更换步骤 →
          </Link>
        </div>
        <p className={styles.downloadNote}>无需注册即可下载和本地使用</p>
      </div>
    </section>
  );
}

export function AppearanceGuide() {
  return (
    <section className={styles.guide} aria-labelledby="appearance-guide">
      <div>
        <p className="eyebrow">带到你的桌面</p>
        <h2 id="appearance-guide">选好之后，怎么使用？</h2>
      </div>
      <ol>
        <li>
          <span aria-hidden="true">01</span>
          <div>
            <strong>下载并解压资源</strong>
            <p>先查看作者许可和版本说明。</p>
          </div>
        </li>
        <li>
          <span aria-hidden="true">02</span>
          <div>
            <strong>在客户端打开“更换形象”</strong>
            <p>本地导入图片、动图或导出的 Live2D 模型。</p>
          </div>
        </li>
        <li>
          <span aria-hidden="true">03</span>
          <div>
            <strong>点击“使用这个形象”</strong>
            <p>以客户端实际试载结果为准。</p>
          </div>
        </li>
      </ol>
      <p className={styles.guideNote}>
        网页负责浏览和下载，不会直接切换桌面上的形象。
        <Link className="quiet-link" href="/docs/appearance">
          查看详细教程 →
        </Link>
      </p>
    </section>
  );
}
