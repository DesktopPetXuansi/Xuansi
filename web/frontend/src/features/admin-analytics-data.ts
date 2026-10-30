import { z } from "zod";

export const analyticsRanges = [
  { value: "7d", label: "近7天" },
  { value: "30d", label: "近30天" },
  { value: "90d", label: "近90天" },
] as const;

export type AnalyticsRange = (typeof analyticsRanges)[number]["value"];
const count = z.number().int().nonnegative();

// 服务端来源失败使用 null；保留这一边界，避免缺失统计被解释为零。
export const analyticsSchema = z.object({
  range: z.enum(["7d", "30d", "90d"]),
  traffic: z
    .object({
      visitors: count,
      pageviews: count,
      visits: count,
      downloadClicks: count.nullable(),
      trend: z.array(
        z.object({
          date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
          pageviews: count,
        }),
      ),
    })
    .nullable(),
  downloads: z
    .object({
      total: count,
      versions: z.array(
        z.object({
          version: z.string(),
          filename: z.string(),
          count,
        }),
      ),
    })
    .nullable(),
});

export type Analytics = z.infer<typeof analyticsSchema>;
export type AnalyticsTraffic = NonNullable<Analytics["traffic"]>;
export const analyticsNumber = new Intl.NumberFormat("zh-CN");
