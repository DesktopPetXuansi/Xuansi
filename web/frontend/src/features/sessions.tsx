"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Session } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function Sessions() {
  return (
    <>
      <Heading title="会话与客户端授权">
        撤销不再使用的设备。客户端授权只允许读取资源。
      </Heading>
      <SessionList endpoint="/me/sessions" title="网站会话" />
      <SessionList endpoint="/me/client-grants" title="客户端授权" />
    </>
  );
}
function SessionList({ endpoint, title }: { endpoint: string; title: string }) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: [endpoint],
    queryFn: () => api<Session[]>(endpoint),
  });
  const [error, setError] = useState<unknown>();
  async function revoke(id: string) {
    try {
      await api(`${endpoint}/${id}`, "DELETE");
      await cache.invalidateQueries({ queryKey: [endpoint] });
      await cache.invalidateQueries({ queryKey: ["me"] });
    } catch (cause) {
      setError(cause);
    }
  }
  return (
    <section style={{ marginBottom: 30 }}>
      <h2>{title}</h2>
      {query.isPending && <Notice>正在加载…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>没有记录。</Notice>
      )}
      {query.data?.map((item) => (
        <article className="row" key={item.id}>
          <div className="row-body">
            <h3>
              {item.isCurrent ? "当前会话" : (item.deviceLabel ?? "网站会话")}
            </h3>
            <p>创建于 {new Date(item.createdAt).toLocaleString("zh-CN")}</p>
          </div>
          <Button className="secondary" onClick={() => revoke(item.id)}>
            撤销
          </Button>
        </article>
      ))}
    </section>
  );
}
