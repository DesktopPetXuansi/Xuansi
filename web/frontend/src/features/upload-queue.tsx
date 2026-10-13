"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Upload, statuses } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function UploadQueue() {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["uploads"],
    queryFn: () => api<Upload[]>("/me/uploads"),
    refetchInterval: (state) =>
      state.state.data?.some((item) =>
        ["CREATED", "UPLOADED", "VALIDATING"].includes(item.status),
      )
        ? 2000
        : false,
  });
  const [error, setError] = useState<unknown>();
  async function cancel(id: string) {
    try {
      await api(`/uploads/${id}`, "DELETE");
      await cache.invalidateQueries({ queryKey: ["uploads"] });
    } catch (cause) {
      setError(cause);
    }
  }
  return (
    <>
      <Heading title="上传队列">
        文件上传完成后由后台校验；只有就绪版本可以下载。
      </Heading>
      {query.isPending && <Notice>正在加载上传任务…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>目前没有上传任务。</Notice>
      )}
      {query.data?.map((item) => (
        <article className="row" key={item.id}>
          <div className="row-body">
            <code>{item.id}</code>
            <p>
              <span className="badge">
                {statuses[item.status] ?? item.status}
              </span>
              {item.errorCode}
            </p>
          </div>
          {["CREATED", "UPLOADED"].includes(item.status) && (
            <Button className="secondary" onClick={() => cancel(item.id)}>
              取消上传
            </Button>
          )}
        </article>
      ))}
    </>
  );
}
