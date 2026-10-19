"use client";
import { useMe } from "@/features/identity/session";
import { Heading, Notice } from "@/components/ui";
import { HistoryRow } from "@/features/history/history-row";
import { useRecentAppearances } from "@/features/history/queries";
import { useLibrary } from "@/features/library/queries";
import Link from "next/link";

export function CompanionPage() {
  const me = useMe();
  const history = useRecentAppearances();
  const library = useLibrary();
  const recent = history.data?.data ?? [];
  const latest = recent[0];
  return <>
    <Heading eyebrow={`你好，${me.data?.displayName || "朋友"}`} title="我的桌宠">找回喜欢的形象，接着上一次的陪伴。</Heading>
    <section className="companion-current" aria-labelledby="current-appearance">
      <p className="eyebrow">你的形象</p>
      <h2 id="current-appearance">最近同步的形象</h2>
      {history.isPending ? <Notice>正在查看同步记录…</Notice> : history.error ? <Notice error={history.error} /> : latest ? <>
        <p className="companion-name">{latest.name}</p>
        <p className="muted">同步记录：<time dateTime={latest.occurredAt}>{new Date(latest.occurredAt).toLocaleString("zh-CN")}</time>{latest.deviceLabel ? ` · ${latest.deviceLabel}` : ""}</p>
        {latest.resourceId && latest.available ? <Link className="button-link" href={`/resources/${encodeURIComponent(latest.resourceId)}`}>查看这个形象</Link> : <p className="muted">{latest.resourceId ? "资源目前不可访问，请在原设备查看已保存的形象。" : "这是本机形象，请在桌面客户端选择或恢复默认形象。"}</p>}
      </> : <><p>还没有同步的形象。</p><p className="muted">在桌面客户端主动开启历史同步后，会在这里看到最近使用的形象。本机记录不会自动上传。</p><Link className="button-link" href="/resources">挑一个喜欢的形象</Link></>}
    </section>
    <section className="companion-section" aria-labelledby="recent-history">
      <div className="section-heading"><h2 id="recent-history">最近使用</h2><Link className="quiet-link" href="/dashboard/history">全部历史 →</Link></div>
      {!history.isPending && !history.error && recent.length === 0 && <p className="muted">实际使用并同步后，记录会出现在这里；预览和下载不算使用。</p>}
      {recent.map(item => <HistoryRow key={item.id} item={item} />)}
    </section>
    <section className="companion-section" aria-labelledby="favorite-resources">
      <div className="section-heading"><h2 id="favorite-resources">收藏</h2><Link className="quiet-link" href="/dashboard/library">全部收藏 →</Link></div>
      {library.isPending && <Notice>正在加载收藏…</Notice>}
      {library.error && <Notice error={library.error} />}
      {!library.isPending && !library.error && !library.data?.length && <p className="muted">遇到喜欢的资源可以先收藏，之后再带到桌面。<Link className="quiet-link" href="/resources">浏览资源库</Link></p>}
      {library.data?.slice(0, 3).map(({ resource }) => <article className="row" key={resource.id}><div className="row-body"><h3>{resource.name}</h3><p>{resource.description}</p></div><Link className="quiet-link" href={`/resources/${encodeURIComponent(resource.id)}`}>查看资源</Link></article>)}
    </section>
    <p className="muted companion-note">想分享自己的作品？<Link className="quiet-link" href="/dashboard/resources">打开上传管理</Link>。聊天、记忆和 AI 模型密钥保留在本机。</p>
  </>;
}
