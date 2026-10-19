"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { HistoryRow } from "./history-row";
import { useHistory } from "./queries";
import type { HistoryKind } from "./types";

export function HistoryPage() {
  const [kind, setKind] = useState<HistoryKind>("APPEARANCE");
  return <><Heading title="使用历史">形象使用记录来自你主动开启的客户端同步。下载记录只表示文件下载完成，不表示已经使用。</Heading>
    <div className="actions history-tabs" role="group" aria-label="历史类别">
      {(["APPEARANCE", "DOWNLOAD"] as const).map(value => <Button key={value} className={kind === value ? "" : "secondary"} aria-pressed={kind === value} onClick={() => { setKind(value); console.debug("[历史] 切换类别"); }}>{value === "APPEARANCE" ? "形象使用" : "下载记录"}</Button>)}
    </div><HistoryList key={kind} kind={kind} /></>;
}
function HistoryList({ kind }: { kind: HistoryKind }) {
  const query = useHistory(kind);
  const cache = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const entries = query.data?.pages.flatMap(page => page.data) ?? [];
  async function remove(id?: string) {
    setBusy(true); setError(undefined);
    try {
      await api(id ? `/me/history/${encodeURIComponent(id)}` : `/me/history?kind=${kind}`, "DELETE");
      await cache.invalidateQueries({ queryKey: ["history"] });
      setConfirmClear(false);
      console.debug("[历史] 记录已删除", id ? "单条" : "当前类别");
    } catch (cause) { setError(cause); }
    finally { setBusy(false); }
  }
  return <section aria-label={kind === "APPEARANCE" ? "形象使用记录" : "下载记录列表"}>
    {query.isPending && <Notice>正在加载历史…</Notice>}
    {query.error && <><Notice error={query.error} /><Button className="secondary" onClick={() => query.refetch()}>重新加载</Button></>}
    {error !== undefined && <Notice error={error} />}
    {!query.isPending && !query.error && entries.length === 0 && <Notice>{kind === "APPEARANCE" ? "还没有同步的形象使用记录。请在桌面客户端主动开启历史同步；已有的本机记录不会自动上传。" : "还没有下载记录。登录后完成的资源下载会记录在这里。"}</Notice>}
    {entries.map(item => <HistoryRow key={item.id} item={item}><Button className="secondary" disabled={busy} aria-label={`删除 ${item.name} 的记录`} onClick={() => remove(item.id)}>删除</Button></HistoryRow>)}
    {query.hasNextPage && <Button className="secondary" disabled={query.isFetchingNextPage || busy} onClick={() => query.fetchNextPage()}>{query.isFetchingNextPage ? "正在加载…" : "加载更多"}</Button>}
    {entries.length > 0 && <div className="history-clear">
      {confirmClear ? <><p>清空这一类历史？已下载文件、收藏和桌面当前形象都会保留。</p><div className="actions"><Button disabled={busy} onClick={() => remove()}>{busy ? "正在清空…" : "确认清空"}</Button><Button className="secondary" disabled={busy} onClick={() => setConfirmClear(false)}>取消</Button></div></> : <Button className="secondary" disabled={busy} onClick={() => setConfirmClear(true)}>清空{kind === "APPEARANCE" ? "形象使用" : "下载"}记录</Button>}
    </div>}
  </section>;
}
