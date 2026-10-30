"use client";

import { Button, Heading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useMe } from "./identity/session";
import {
  analyticsRanges,
  analyticsSchema,
  type AnalyticsRange,
} from "./admin-analytics-data";
import {
  AnalyticsDownloads,
  AnalyticsTrafficOverview,
} from "./admin-analytics-sections";
import styles from "./admin-analytics.module.css";

// 查询键包含账号与范围，切换身份时不会借用上一账号的统计缓存。
export function AdminAnalytics() {
  const me = useMe();
  const identity = me.data?.id ?? "";
  const [range, setRange] = useState<AnalyticsRange>("7d");
  const query = useQuery({
    queryKey: ["admin-analytics", identity, range],
    enabled: me.data?.role === "ADMIN",
    queryFn: async ({ signal }) => {
      const payload = await api<unknown>(
        `/admin/analytics?range=${range}`,
        "GET",
        undefined,
        false,
        { signal },
      );
      const parsed = analyticsSchema.safeParse(payload);
      if (!parsed.success || parsed.data.range !== range) {
        console.warn("[访问统计] 统计响应格式无效");
        throw new Error("统计数据格式无法识别，请稍后重试。");
      }
      return parsed.data;
    },
  });

  function refresh() {
    console.debug("[访问统计] 重新读取统计");
    void query.refetch();
  }

  if (me.isPending) return <Notice>正在确认管理员身份…</Notice>;
  if (me.error) return <Notice error={me.error} />;
  if (me.data?.role !== "ADMIN")
    return <Notice>需要管理员账号才能查看统计。</Notice>;

  return (
    <>
      <Heading eyebrow="ADMINISTRATION / 管理" title="访问统计">
        了解网站访问与客户端下载情况。匿名统计不展示访客真实身份。
      </Heading>
      <div className={styles.toolbar}>
        <fieldset className={styles.ranges}>
          <legend>访问统计范围</legend>
          <div>
            {analyticsRanges.map((option) => (
              <Button
                key={option.value}
                className="secondary"
                aria-pressed={range === option.value}
                onClick={() => {
                  setRange(option.value);
                  console.debug("[访问统计] 已切换统计范围", option.value);
                }}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </fieldset>
        <Button
          className="secondary"
          disabled={query.isFetching}
          onClick={refresh}
        >
          刷新统计
        </Button>
      </div>
      <p className={styles.note}>
        访问数据按北京时间统计；安装包下载量为所有版本累计，最新数据可能延迟约5分钟。
      </p>
      {query.isPending ? (
        <Notice>正在加载统计…</Notice>
      ) : query.error ? (
        <>
          <Notice error={query.error} />
          <Button className="secondary" onClick={refresh}>
            重试读取统计
          </Button>
        </>
      ) : query.data ? (
        <div className={styles.sections} aria-busy={query.isFetching}>
          {query.isFetching && <p role="status">正在刷新统计…</p>}
          <AnalyticsTrafficOverview traffic={query.data.traffic} />
          <AnalyticsDownloads downloads={query.data.downloads} />
        </div>
      ) : null}
    </>
  );
}
