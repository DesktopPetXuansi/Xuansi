"use client";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { apiPage, safeUrl } from "@/lib/api";
import { type Resource, kinds, statuses } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
export { VersionList } from "./version-list";
export function ResourceList({ personal = false }: { personal?: boolean }) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [filter, setFilter] = useState({
    search: "",
    kind: "",
    tag: "",
    cursor: "",
  });
  const [tag, setTag] = useState("");
  const query = useQuery({
    queryKey: ["resources", personal, filter],
    queryFn: () =>
      apiPage<Resource>(
        `${personal ? "/me/resources" : "/resources"}?${new URLSearchParams(filter)}`,
      ),
  });
  return (
    <>
      <Heading
        eyebrow={
          personal ? "CREATOR / 创作者工作台" : "RESOURCE LIBRARY / 资源库"
        }
        title={personal ? "我的资源" : "找到你的下一种形象。"}
      >
        {personal
          ? "上传默认私有，保留作者、许可和版本信息。"
          : "浏览已发布的官方资源，按模型版本选择动作与表情。"}
      </Heading>
      <div className="actions" style={{ marginBottom: 24 }}>
        {personal && (
          <Link href="/dashboard/resources/new" className="button-link">
            新建资源 +
          </Link>
        )}
      </div>
      <form
        className="filters"
        onSubmit={(event) => {
          event.preventDefault();
          setFilter({ search, kind, tag, cursor: "" });
        }}
      >
        <Field label="搜索资源">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="名称或标签"
          />
        </Field>
        <Field label="资源类型">
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">所有类型</option>
            {Object.entries(kinds).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Button type="submit">筛选</Button>
        <Field label="标签">
          <input
            value={tag}
            onChange={(event) => setTag(event.target.value)}
            placeholder="按标签筛选"
          />
        </Field>
      </form>
      {query.isPending ? (
        <Notice>正在加载资源…</Notice>
      ) : query.error ? (
        <Notice error={query.error} />
      ) : query.data?.data.length ? (
        query.data.data.map((resource) => (
          <ResourceRow
            key={resource.id}
            resource={resource}
            personal={personal}
          />
        ))
      ) : (
        <Notice>
          暂时没有符合条件的资源。
          {personal
            ? "可以先创建资源，再上传第一个版本。"
            : "官方发布后将在这里显示。"}
        </Notice>
      )}
      <div className="actions" style={{ marginTop: 24 }}>
        {filter.cursor && (
          <Button
            className="secondary"
            onClick={() => setFilter({ ...filter, cursor: "" })}
          >
            返回首页
          </Button>
        )}
        {query.data?.meta?.nextCursor && (
          <Button
            className="secondary"
            onClick={() =>
              setFilter({
                ...filter,
                cursor: query.data?.meta?.nextCursor ?? "",
              })
            }
          >
            下一页 →
          </Button>
        )}
      </div>
    </>
  );
}
export function ResourceRow({
  resource,
  personal = false,
}: {
  resource: Resource;
  personal?: boolean;
}) {
  return (
    <Link
      href={`${personal ? "/dashboard" : ""}/resources/${resource.id}`}
      className="resource-link"
    >
      <article className="row">
        {resource.coverUrl ? (
          <Image
            unoptimized
            className="resource-thumb"
            src={safeUrl(resource.coverUrl)}
            alt=""
            width={78}
            height={90}
          />
        ) : (
          <div className="resource-placeholder" aria-hidden>
            ◇
          </div>
        )}
        <div className="row-body">
          <h3>{resource.name}</h3>
          <p>{resource.description || "作者尚未添加介绍。"}</p>
          <span className="badge">{kinds[resource.kind] ?? resource.kind}</span>
          <span className="badge">{statuses[resource.visibility]}</span>
          <small className="muted">
            {resource.author || "未署名"} · {resource.license || "未声明许可"}
          </small>
        </div>
        <span aria-hidden>↗</span>
      </article>
    </Link>
  );
}

export { ResourceDetail } from "./resource-detail";
