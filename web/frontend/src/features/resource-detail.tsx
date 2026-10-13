"use client";
import { useMe } from "@/components/navigation";
import { Button, Heading, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { type Resource, kinds, statuses } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { VersionList } from "./version-list";
export function ResourceDetail({ id }: { id: string }) {
  const resource = useQuery({
    queryKey: ["resource", id],
    queryFn: () => api<Resource>(`/resources/${id}`),
  });
  const me = useMe();
  const cache = useQueryClient();
  const add = useMutation({
    mutationFn: () => api(`/me/library/${id}`, "PUT", {}),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["library"] }),
  });
  if (resource.isPending) return <Notice>正在读取资源…</Notice>;
  if (resource.error) return <Notice error={resource.error} />;
  if (!resource.data) return null;
  const item = resource.data;
  return (
    <>
      <Heading eyebrow={kinds[item.kind]} title={item.name}>
        {item.description}
      </Heading>
      <div className="split">
        <section>
          <h2>资源版本</h2>
          <VersionList id={id} />
        </section>
        <aside className="panel">
          <h3>使用前，请了解</h3>
          <p>作者：{item.author || "未填写"}</p>
          <p>许可：{item.license || "未声明"}</p>
          <p>范围：{statuses[item.visibility]}</p>
          {item.source && (
            <p>
              <a
                className="quiet-link"
                href={safeUrl(item.source)}
                rel="noreferrer"
                target="_blank"
              >
                资源来源 ↗
              </a>
            </p>
          )}
          <div>
            {item.tags.map((tag) => (
              <span className="badge" key={tag}>
                {tag}
              </span>
            ))}
          </div>
          <p className="legal-note">
            网站校验不代表任意模型兼容。客户端接入版会验证摘要并试载，下载前请确认作者许可。
          </p>
          {me.data ? (
            <Button disabled={add.isPending} onClick={() => add.mutate()}>
              {add.isSuccess ? "已加入资源库" : "加入我的资源库"}
            </Button>
          ) : (
            <Link
              className="button-link"
              href={`/login?returnTo=/resources/${id}`}
            >
              登录后加入资源库
            </Link>
          )}
          {add.error && <Notice error={add.error} />}
        </aside>
      </div>
    </>
  );
}
