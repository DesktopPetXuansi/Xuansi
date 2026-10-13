"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Resource } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { LibraryItem } from "./library-item";
export function Library() {
  const query = useQuery({
    queryKey: ["library"],
    queryFn: () =>
      api<{ resource: Resource; pinnedVersionId: string | null }[]>(
        "/me/library",
      ),
  });
  const cache = useQueryClient();
  const [error, setError] = useState<unknown>();
  async function remove(id: string) {
    try {
      await api(`/me/library/${id}`, "DELETE");
      await cache.invalidateQueries({ queryKey: ["library"] });
    } catch (cause) {
      setError(cause);
    }
  }
  return (
    <>
      <Heading title="我的资源库">
        客户端授权后可以读取这里的资源。选择精确版本，保持安装结果可复现。
      </Heading>
      {query.isPending && <Notice>正在加载资源库…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>
          还没有加入资源。
          <Link href="/resources" className="quiet-link">
            浏览官方资源
          </Link>
        </Notice>
      )}
      {query.data?.map((item) => (
        <section key={item.resource.id}>
          <LibraryItem
            resource={item.resource}
            pinnedVersionId={item.pinnedVersionId}
          />
          <div className="actions">
            <small className="muted">
              固定版本：{item.pinnedVersionId ?? "使用当前版本"}
            </small>
            <Button
              className="secondary"
              onClick={() => remove(item.resource.id)}
            >
              移出资源库
            </Button>
          </div>
        </section>
      ))}
    </>
  );
}
