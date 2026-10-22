"use client";
import { Button, Field, Heading, Notice } from "@/components/ui";
import { apiPage, safeUrl } from "@/lib/api";
import { type Resource, kinds, statuses } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import styles from "./resources.module.css";
export { VersionList } from "./version-list";

export function ResourceList({ personal = false }: { personal?: boolean }) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [filter, setFilter] = useState({
    search: "",
    kind: "",
    tag: "",
    cursor: "",
  });
  const query = useQuery({
    queryKey: ["resources", personal, filter],
    queryFn: ({ signal }) =>
      apiPage<Resource>(
        `${personal ? "/me/resources" : "/resources"}?${new URLSearchParams(filter)}`,
        { signal },
      ),
  });
  const filtered = Boolean(filter.search || filter.kind || filter.tag);
  function clearFilters() {
    setSearch("");
    setKind("");
    setTag("");
    setFilter({ search: "", kind: "", tag: "", cursor: "" });
    console.debug("[资源筛选] 已清除筛选条件");
  }
  return (
    <>
      <Heading
        eyebrow={personal ? "创作者工作台" : "桌宠形象"}
        title={personal ? "我的资源" : "选一个喜欢的桌面伙伴。"}
      >
        {personal
          ? "上传默认私有，保留作者、许可和版本信息。"
          : "可以使用自带的玄司，也可以导入自己的图片、动图或 Live2D 形象。"}
      </Heading>
      {personal ? (
        <div className="actions resource-create">
          <Link href="/dashboard/resources/new" className="button-link">
            新建资源 +
          </Link>
        </div>
      ) : (
        <section
          className={styles.libraryIntro}
          aria-labelledby="builtin-appearance"
        >
          <Image
            src="/brand/front.png"
            alt="客户端自带的玄司形象"
            width={160}
            height={180}
          />
          <div>
            <h2 id="builtin-appearance">先和玄司见个面</h2>
            <p>
              客户端自带形象，安装后就能使用。换成自己的形象也不需要先上传到网站。
            </p>
            <div className="actions">
              <Link className="button-link" href="/download">
                下载客户端
              </Link>
              <Link className="quiet-link" href="/docs/appearance">
                怎么更换形象 →
              </Link>
            </div>
          </div>
        </section>
      )}
      {!personal && (
        <div className={styles.browseHeading}>
          <h2>浏览已发布资源</h2>
          <Link className="quiet-link" href="/dashboard/resources/new">
            我想分享形象 →
          </Link>
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFilter({ search, kind, tag, cursor: "" });
          console.debug("[资源筛选] 已提交筛选条件");
        }}
      >
        <div className={styles.search}>
          <Field label="搜索名称">
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="找找喜欢的形象"
            />
          </Field>
          <Field label="想找哪一种">
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              <option value="">全部资源（含动作与表情）</option>
              {Object.entries(kinds).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className={styles.filterActions}>
          <details className={styles.advanced}>
            <summary>按标签进一步筛选</summary>
            <Field label="标签">
              <input
                value={tag}
                onChange={(event) => setTag(event.target.value)}
                placeholder="填写标签后点击搜索"
              />
            </Field>
          </details>
          <div className="actions">
            {filtered && (
              <Button
                type="button"
                className="secondary"
                onClick={clearFilters}
              >
                清除筛选
              </Button>
            )}
            <Button type="submit">搜索</Button>
          </div>
        </div>
      </form>
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
            />
          ))}
        </div>
      ) : (
        <section className={styles.empty} role="status">
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
                : "不影响使用桌宠：玄司已随客户端提供，你也可以导入自己的形象。"}
          </p>
          {!personal && (
            <Link className="quiet-link" href="/docs/appearance">
              查看换形象的步骤 →
            </Link>
          )}
        </section>
      )}
      <div className="actions" style={{ marginTop: 24 }}>
        {filter.cursor && (
          <Button
            className="secondary"
            onClick={() => setFilter({ ...filter, cursor: "" })}
          >
            返回第一页
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
  // 公开卡片优先呈现形象；创作者列表继续显示可见范围，方便管理。
  return (
    <Link
      href={`${personal ? "/dashboard" : ""}/resources/${resource.id}`}
      className={personal ? "resource-link" : styles.card}
    >
      <article className={personal ? "row" : undefined}>
        {resource.coverUrl ? (
          <Image
            unoptimized
            className={personal ? "resource-thumb" : styles.preview}
            src={safeUrl(resource.coverUrl)}
            alt={`${resource.name}预览`}
            width={personal ? 78 : 360}
            height={personal ? 90 : 240}
          />
        ) : (
          <div
            className={
              personal
                ? "resource-placeholder"
                : `${styles.preview} ${styles.placeholder}`
            }
            aria-hidden
          >
            {personal ? "◇" : "作者暂未提供预览图"}
          </div>
        )}
        <div className={personal ? "row-body" : styles.cardBody}>
          {!personal && (
            <span className={styles.kind}>
              {kinds[resource.kind] ?? resource.kind}
            </span>
          )}
          <h2 className="resource-title">{resource.name}</h2>
          <p>{resource.description || "作者尚未添加介绍。"}</p>
          {personal && (
            <>
              <span className="badge">
                {kinds[resource.kind] ?? resource.kind}
              </span>
              <span className="badge">{statuses[resource.visibility]}</span>
            </>
          )}
          <small className="muted">
            {resource.author || "未署名"} · {resource.license || "未声明许可"}
          </small>
          {!personal && <span className="quiet-link">查看介绍与下载 →</span>}
        </div>
      </article>
    </Link>
  );
}
export { ResourceDetail } from "./resource-detail";
