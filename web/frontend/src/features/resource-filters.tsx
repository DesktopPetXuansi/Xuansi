"use client";

import { Button, Field } from "@/components/ui";
import { kinds } from "@/lib/types";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import styles from "./resources.module.css";

export type ResourceFilters = {
  group: string;
  kind: string;
  search: string;
  tag: string;
  cursor: string;
};

// URL是已应用条件的唯一来源，浏览器后退和刷新都能恢复筛选。
export function useResourceFilters(personal: boolean) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const group = personal
    ? ""
    : params.get("group") === "ADDON"
      ? "ADDON"
      : "APPEARANCE";
  const available = personal
    ? Object.keys(kinds)
    : group === "ADDON"
      ? ["MOTION", "EXPRESSION"]
      : ["MODEL", "IMAGE", "ANIMATION"];
  const kind = params.get("kind") ?? "";
  const filter = {
    group,
    kind: available.includes(kind) ? kind : "",
    search: params.get("search") ?? "",
    tag: params.get("tag") ?? "",
    cursor: params.get("cursor") ?? "",
  };
  function apply(next: Partial<ResourceFilters>, keepCursor = false) {
    const updated = {
      ...filter,
      cursor: keepCursor ? filter.cursor : "",
      ...next,
    };
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(updated))
      if (value) query.set(name, value);
    router.push(`${pathname}${query.size ? `?${query}` : ""}`, {
      scroll: false,
    });
    console.debug("[资源浏览] 已更新筛选或分页");
  }
  return { filter, available, apply };
}

// 表单以已应用条件为key重新建立，URL切换无需effect回填输入框。
export function ResourceFilterForm({
  filter,
  available,
  onApply,
}: {
  filter: ResourceFilters;
  available: string[];
  onApply: (next: Partial<ResourceFilters>) => void;
}) {
  const [search, setSearch] = useState(filter.search);
  const [tag, setTag] = useState(filter.tag);
  const filtered = !!(filter.search || filter.kind || filter.tag);
  return (
    <form
      className={styles.filterForm}
      onSubmit={(event) => {
        event.preventDefault();
        onApply({ search: search.trim(), tag: tag.trim() });
      }}
    >
      <div className={styles.search}>
        <Field label="搜索名称">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="输入形象或资源名称"
          />
        </Field>
        <Field label="想找哪一种">
          <select
            aria-label="想找哪一种"
            value={filter.kind}
            onChange={(event) =>
              onApply({
                kind: event.target.value,
                search: search.trim(),
                tag: tag.trim(),
              })
            }
          >
            <option value="">
              {filter.group === "APPEARANCE"
                ? "全部形象"
                : filter.group === "ADDON"
                  ? "全部配套资源"
                  : "全部资源"}
            </option>
            {available.map((kind) => (
              <option value={kind} key={kind}>
                {kinds[kind]}
              </option>
            ))}
          </select>
        </Field>
        <Button type="submit">搜索</Button>
      </div>
      <div className={styles.filterActions}>
        <details
          className={styles.advanced}
          open={filter.tag ? true : undefined}
        >
          <summary>按标签筛选</summary>
          <Field label="标签">
            <input
              value={tag}
              onChange={(event) => setTag(event.target.value)}
              placeholder="输入作者提供的标签"
            />
          </Field>
        </details>
        {filtered && (
          <Button
            type="button"
            className="secondary"
            onClick={() => onApply({ search: "", kind: "", tag: "" })}
          >
            清除筛选
          </Button>
        )}
      </div>
    </form>
  );
}
