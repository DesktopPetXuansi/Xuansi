"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Grant, type Session } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function Sessions() {
  return (
    <>
      <Heading title="会话与客户端授权">
        查看网站会话和已授权的客户端。资源读取、模型上传和历史同步分别授权；撤销后客户端需重新获得许可。
      </Heading>
      <SessionList endpoint="/me/sessions" title="网站会话" />
      <SessionList endpoint="/me/client-grants" title="客户端授权" />
    </>
  );
}
function SessionList({
  endpoint,
  title,
}: {
  endpoint: "/me/sessions" | "/me/client-grants";
  title: string;
}) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: [endpoint],
    queryFn: () => api<(Session | Grant)[]>(endpoint),
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
              {"isCurrent" in item && item.isCurrent
                ? "当前会话"
                : "deviceLabel" in item
                  ? item.deviceLabel
                  : "网站会话"}
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
