"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useLibrary } from "./queries";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { LibraryItem } from "../library-item";
export function Library() {
  const query = useLibrary();
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
      <Heading title="收藏">
        这里保留你主动收藏的资源，可固定喜欢的版本。收藏不代表已经下载或使用。
      </Heading>
      {query.isPending && <Notice>正在加载收藏…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>
          还没有收藏。
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
              取消收藏
            </Button>
          </div>
        </section>
      ))}
    </>
  );
}
