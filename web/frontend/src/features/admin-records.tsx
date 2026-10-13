"use client";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
export function Records({ endpoint }: { endpoint: string }) {
  const query = useQuery({
    queryKey: ["admin", endpoint],
    queryFn: () => api<Record<string, unknown>[]>(`/admin/${endpoint}`),
  });
  return (
    <>
      {query.isPending && <Notice>正在加载记录…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>目前没有记录。</Notice>
      )}
      {query.data?.map((record, index) => (
        <details className="version-row" key={String(record.id ?? index)}>
          <summary>
            {String(record.type ?? record.action ?? record.id ?? "记录")} ·{" "}
            {String(record.status ?? record.createdAt ?? "")}
          </summary>
          <pre>{JSON.stringify(record, null, 2)}</pre>
        </details>
      ))}
    </>
  );
}
