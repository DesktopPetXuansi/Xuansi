"use client";

import { clientRelease } from "@/lib/client-release";
import { ChevronDown, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import styles from "../releases.module.css";

// 校验只读取本地文件摘要，不下载或执行任何脚本。
export function PackageChecksum() {
  const [copyStatus, setCopyStatus] = useState("");

  async function copyChecksum() {
    try {
      await navigator.clipboard.writeText(clientRelease.sha256);
      setCopyStatus("已复制 SHA-256 摘要。");
    } catch (error) {
      console.warn("[download] 无法复制安装包摘要", error);
      setCopyStatus("复制失败，请长按或选中下方完整摘要后手动复制。");
    }
  }

  return (
    <Collapsible className={styles.details}>
      <CollapsibleTrigger asChild>
        <Button type="button" variant="ghost" className={styles.detailsTrigger}>
          查看 SHA-256 校验与安装安全说明
          <ChevronDown size={16} aria-hidden />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p>
          安装包来自项目官方
          GitHub，目前未进行代码签名。校验一致表示文件与公开摘要一致，不能替代代码签名或安全软件检测。
        </p>
        <p>
          文件：<code>{clientRelease.filename}</code>
        </p>
        <p>
          SHA-256：
          <code className={styles.checksum}>{clientRelease.sha256}</code>
        </p>
        <div className={styles.checksumActions}>
          <Button

            variant="outline"
            type="button"
            onClick={copyChecksum}
          >
            <Copy size={16} aria-hidden />
            复制摘要
          </Button>
          <Button
            asChild
            variant="link"
            className="h-auto px-0 py-0 whitespace-normal"
          >
            <a
              className="quiet-link"
              href={clientRelease.checksumUrl}
              target="_blank"
              rel="noreferrer"
            >
              官方 SHA256SUMS 校验文件 ↗
            </a>
          </Button>
        </div>
        <p role="status" aria-live="polite">
          {copyStatus}
        </p>
        <ol className={styles.verifySteps}>
          <li>下载完成后，在安装包所在文件夹打开 PowerShell。</li>
          <li>运行下方命令，只计算文件摘要：</li>
        </ol>
        <pre className={styles.command}>
          <code>{`Get-FileHash -LiteralPath '.\\${clientRelease.filename}' -Algorithm SHA256`}</code>
        </pre>
        <p>
          将输出的 Hash
          与上述摘要和官方校验文件逐字对照。如果不一致，请停止安装并从官方发行页重新下载。无需执行其他脚本或关闭系统安全防护。
        </p>
      </CollapsibleContent>
    </Collapsible>
  );
}
