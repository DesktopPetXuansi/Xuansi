import { analyticsNumber, type AnalyticsTraffic } from "./admin-analytics-data";
import styles from "./admin-analytics.module.css";

// 日期由服务端按北京时间分桶；直接显示日期文本，避免浏览器时区重新偏移。
export function AnalyticsTrend({ trend }: Pick<AnalyticsTraffic, "trend">) {
  if (!trend.length)
    return <p className={styles.empty}>所选时间暂无访问记录。</p>;

  const width = 720;
  const height = 180;
  // 绘图比例至少为 1，展示给管理员的峰值仍须保留真实的零。
  const peak = Math.max(...trend.map((point) => point.pageviews));
  const scale = Math.max(1, peak);
  const points = trend.map((point, index) => ({
    ...point,
    x: trend.length === 1 ? width / 2 : (index / (trend.length - 1)) * width,
    y: height - (point.pageviews / scale) * height,
  }));
  const labels = [
    ...new Set([0, Math.floor((trend.length - 1) / 2), trend.length - 1]),
  ];

  return (
    <figure className={styles.trend}>
      <figcaption>
        <h3>每日浏览量</h3>
        <span>单位：次 · 北京时间 · 峰值 {analyticsNumber.format(peak)}</span>
      </figcaption>
      <svg
        viewBox={`-4 -4 ${width + 8} ${height + 8}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="每日浏览量趋势"
        className={styles.chart}
      >
        <desc>
          {trend[0].date} 至 {trend.at(-1)?.date}{" "}
          的每日浏览量，完整数值可在下方展开查看。
        </desc>
        <line x1="0" y1="0" x2={width} y2="0" className={styles.gridLine} />
        <line
          x1="0"
          y1={height}
          x2={width}
          y2={height}
          className={styles.gridLine}
        />
        <polyline
          points={points.map((point) => `${point.x},${point.y}`).join(" ")}
          className={styles.trendLine}
        />
        {points.length === 1 && (
          <circle
            cx={points[0].x}
            cy={points[0].y}
            r="4"
            className={styles.trendPoint}
          />
        )}
      </svg>
      <div className={styles.axisLabels} aria-hidden="true">
        {labels.map((index) => <span key={index}>{trend[index].date.slice(5)}</span>)}
      </div>
      <details className={styles.dailyData}>
        <summary>查看每日数据</summary>
        <table className={styles.dailyTable}>
          <caption className={styles.visuallyHidden}>
            每日浏览量明细（北京时间）
          </caption>
          <thead>
            <tr>
              <th scope="col">日期</th>
              <th scope="col">浏览量</th>
            </tr>
          </thead>
          <tbody>
            {trend.map((point) => (
              <tr key={point.date}>
                <th scope="row">{point.date}</th>
                <td>{analyticsNumber.format(point.pageviews)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
