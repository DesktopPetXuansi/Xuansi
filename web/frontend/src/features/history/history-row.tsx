import Link from "next/link";
import type { ReactNode } from "react";
import type { HistoryEntry } from "./types";
export function HistoryRow({ item, children }: { item: HistoryEntry; children?: ReactNode }) {
  return <article className="row history-row">
    <div className="row-body">
      <h3>{item.name}</h3>
      <p>{item.version ? `版本 ${item.version} · ` : ""}<time dateTime={item.occurredAt}>{new Date(item.occurredAt).toLocaleString("zh-CN")}</time>{item.deviceLabel ? ` · ${item.deviceLabel}` : ""}</p>
      {!item.resourceId ? <small className="muted">{item.appearanceKind === "DEFAULT" ? "默认形象，可在桌面端恢复默认。" : "本机形象，请回到原设备选择文件；网站没有可恢复的文件。"}</small> : !item.available ? <small className="muted">资源已失效或当前不可访问，记录仍保留。</small> : null}
    </div>
    <div className="actions">
      {item.resourceId && item.available && <Link className="quiet-link" href={`/resources/${encodeURIComponent(item.resourceId)}${item.resourceVersionId ? `#version-${encodeURIComponent(item.resourceVersionId)}` : ""}`}>查看 / 重新获取</Link>}
      {children}
    </div>
  </article>;
}
