"use client";

import { Button, Heading, Notice } from "@/components/ui";
import { apiPage } from "@/lib/api";
import type { Resource } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Suspense } from "react";
import { AppearanceGuide, BuiltinAppearance } from "./builtin-appearance";
import { ResourceRow } from "./resource-card";
import { ResourceFilterForm, useResourceFilters } from "./resource-filters";
import styles from "./resources.module.css";

export { ResourceRow } from "./resource-card";
export { ResourceDetail } from "./resource-detail";
export { VersionList } from "./version-list";

export function ResourceList({ personal = false }: { personal?: boolean }) {
  return (
    <>
      <Heading
        eyebrow={personal ? "创作者工作台" : "桌宠形象 / APPEARANCES"}
        title={personal ? "我的资源" : "选一个喜欢的桌面伙伴。"}
      >
        {personal
          ? "上传默认私有，保留作者、许可和版本信息。"
          : "从自带的玄司开始，或为桌面换一个你喜欢的外观。"}
      </Heading>
      {personal ? (
        <div className="actions resource-create">
          <Link href="/dashboard/resources/new" className="button-link">
            新建资源 +
          </Link>
        </div>
      ) : (
        <BuiltinAppearance />
      )}
      <Suspense fallback={<Notice>正在准备资源浏览…</Notice>}>
        <ResourceCatalog personal={personal} />
      </Suspense>
      {!personal && <AppearanceGuide />}
    </>
  );
}

// 公开浏览和个人管理共享现有接口；用途分组只改变公开页的默认条件。
function ResourceCatalog({ personal }: { personal: boolean }) {
  const { filter, available, apply } = useResourceFilters(personal);
  const request = new URLSearchParams();
  for (const [name, value] of Object.entries(filter))
    if (value) request.set(name, value);
  const query = useQuery({
    queryKey: ["resources", personal, filter],
    queryFn: ({ signal }) =>
      apiPage<Resource>(
        `${personal ? "/me/resources" : "/resources"}?${request}`,
        { signal },
      ),
  });
  const filtered = !!(filter.search || filter.kind || filter.tag);
  const addon = filter.group === "ADDON";
  return (
    <section
      className={styles.catalog}
      aria-labelledby="resource-catalog-title"
      aria-busy={query.isFetching}
    >
      <div className={styles.browseHeading}>
        <div>
          <h2 id="resource-catalog-title">
            {personal ? "管理已上传资源" : addon ? "动作与表情" : "社区形象"}
          </h2>
          {!personal && (
            <p>
              {addon
                ? "给已有 Live2D 模型搭配使用，不能独立当作桌宠形象。"
                : "浏览作者发布的形象，查看介绍、许可和使用方式。"}
            </p>
          )}
        </div>
        {!personal && (
          <Link className="quiet-link" href="/dashboard/resources/new">
            分享我的形象 ↗
          </Link>
        )}
      </div>
      {!personal && (
        <div className={styles.groups} role="group" aria-label="资源用途">
          <Button
            className="secondary"
            aria-pressed={!addon}
            onClick={() =>
              apply({ group: "APPEARANCE", kind: "", search: "", tag: "" })
            }
          >
            桌宠形象
          </Button>
          <Button
            className="secondary"
            aria-pressed={addon}
            onClick={() =>
              apply({ group: "ADDON", kind: "", search: "", tag: "" })
            }
          >
            动作与表情
          </Button>
        </div>
      )}
      <ResourceFilterForm
        key={`${filter.group}:${filter.kind}:${filter.search}:${filter.tag}`}
        filter={filter}
        available={available}
        onApply={apply}
      />
      {query.isPending ? (
        <Notice>正在寻找已发布的资源…</Notice>
      ) : query.error ? (
        <>
          <Notice error={query.error} />
          <p>
            暂时无法读取资源。你仍然可以使用自带形象，或
            <Link className="quiet-link" href="/docs/appearance">
              查看本地导入方法
            </Link>
            。
          </p>
          <Button className="secondary" onClick={() => void query.refetch()}>
            重新加载
          </Button>
        </>
      ) : query.data?.data.length ? (
        <div className={personal ? undefined : styles.grid}>
          {query.data.data.map((resource) => (
            <ResourceRow
              key={resource.id}
              resource={resource}
              personal={personal}
              headingLevel={personal ? 2 : 3}
            />
          ))}
        </div>
      ) : (
        <section className={styles.empty} role="status">
          <span className={styles.emptyLabel}>
            {filtered
              ? "换个条件再找找"
              : personal
                ? "从第一个资源开始"
                : "你也可以带来自己的形象"}
          </span>
          <h3>
            {filtered
              ? "没有找到符合条件的资源"
              : personal
                ? "还没有上传资源"
                : "这里还没有已发布的资源"}
          </h3>
          <p>
            {filtered
              ? "可以换个名称或类型，也可以清除筛选重新浏览。"
              : personal
                ? "创建一个资源，再上传第一个版本。"
                : addon
                  ? "目前还没有可浏览的配套资源。你仍可在客户端使用自己的模型、动作和表情。"
                  : "可以先使用上方自带的玄司，或在客户端导入自己的形象。"}
          </p>
          {!personal && (
            <Link className="quiet-link" href="/docs/appearance">
              查看换形象的步骤 →
            </Link>
          )}
        </section>
      )}
      {(filter.cursor || query.data?.meta?.nextCursor) && (
        <nav className={styles.pagination} aria-label="资源分页">
          {filter.cursor && (
            <Button
              className="secondary"
              disabled={query.isFetching}
              onClick={() => apply({ cursor: "" }, true)}
            >
              返回第一页
            </Button>
          )}
          {query.data?.meta?.nextCursor && (
            <Button
              className="secondary"
              disabled={query.isFetching}
              onClick={() =>
                apply({ cursor: query.data?.meta?.nextCursor ?? "" }, true)
              }
            >
              下一页 →
            </Button>
          )}
        </nav>
      )}
    </section>
  );
}
