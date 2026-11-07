"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

import Link from "next/link";
import styles from "./resource-upload.module.css";

// 只介绍服务端真正接受的文件；封面和下载文件是两次独立上传。
export function ResourceUploadGuide({
  kind,
  compact = false,
}: {
  kind: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <Collapsible className={styles.guideDetails}>
        <CollapsibleTrigger>查看文件准备说明</CollapsibleTrigger>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <ResourceUploadGuide kind={kind} />
        </CollapsibleContent>
      </Collapsible>
    );
  }
  if (kind !== "MODEL") {
    const description: Record<string, string> = {
      IMAGE: "准备一张 PNG、JPEG 或 WebP 图片作为形象文件。",
      ANIMATION: "准备一个 GIF 动图作为形象文件。",
      MOTION: "准备 .motion3.json 动作文件，并找到对应的模型版本 ID。",
      EXPRESSION: "准备 .exp3.json 表情文件，并找到对应的模型版本 ID。",
    };
    return (
      <aside className={styles.guide} aria-label="上传前准备">
        <h2>先准备好文件</h2>
        <p>{description[kind]}</p>
        <p>封面图片可以稍后单独上传，不会代替实际使用的文件。</p>
      </aside>
    );
  }

  return (
    <aside className={styles.guide} aria-label="Live2D 上传前准备">
      <h2>先准备一个 Live2D 模型压缩包</h2>
      <p>
        在 Live2D Cubism 中导出运行文件，将整个导出文件夹压缩成一个
        <strong> .zip 文件（ZIP 压缩包）</strong>
        。请保留文件和文件夹原来的位置。
      </p>
      <ul>
        <li>
          压缩包需要包含 <code>.model3.json</code>、它引用的 <code>.moc3</code>{" "}
          和贴图。
        </li>
        <li>
          <code>.cmo3</code>{" "}
          是编辑工程，不能直接上传；请先导出运行文件，压缩包里不要放入工程或 PSD
          源文件。
        </li>
        <li>只有一个模型入口时会自动识别，不需要自己填写路径。</li>
        <li>压缩包解压后最多 512 MiB，最多包含 2048 个条目。</li>
      </ul>
      <Collapsible className={styles.example}>
        <CollapsibleTrigger>看看压缩包里应该有什么</CollapsibleTrigger>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <pre>{`角色.zip
└─ 角色文件夹/
   ├─ 角色.model3.json
   ├─ 角色.moc3
   └─ 贴图文件夹/…`}</pre>
          <p>目录名称可以不同；请一并保留模型引用的其他文件。</p>
        </CollapsibleContent>
      </Collapsible>
      <p className={styles.alternative}>
        不方便自己打包？在桌面客户端的“更换形象 → 上传分享”选择模型文件夹或
        <code> .model3.json</code>，客户端会整理引用文件。也可以先
        <Link href="/docs/appearance" className="quiet-link">
          查看换形象帮助
        </Link>
        。
      </p>
    </aside>
  );
}

export function ResourceUploadSteps({ current }: { current: 1 | 2 }) {
  return (
    <ol className={styles.steps} aria-label="上传步骤">
      <li aria-current={current === 1 ? "step" : undefined}>
        <span>1</span>填写作品资料
      </li>
      <li aria-current={current === 2 ? "step" : undefined}>
        <span>2</span>选择文件并上传
      </li>
      <li>
        <span>3</span>校验并选择版本
      </li>
    </ol>
  );
}
