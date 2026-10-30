import { Notice } from "@/components/ui";
import { analyticsNumber, type Analytics } from "./admin-analytics-data";
import { AnalyticsTrend } from "./admin-analytics-trend";
import styles from "./admin-analytics.module.css";

export function AnalyticsTrafficOverview({
  traffic,
}: Pick<Analytics, "traffic">) {
  const metrics = [
    { label: "访客人数（估算）", value: traffic?.visitors, unit: "位" },
    { label: "浏览量", value: traffic?.pageviews, unit: "次" },
    { label: "访问次数", value: traffic?.visits, unit: "次" },
    { label: "下载入口点击", value: traffic?.downloadClicks, unit: "次" },
  ];
  return (
    <section aria-label="网站访问概览">
      <h2 className={styles.sectionTitle}>网站访问</h2>
      <dl className={styles.metrics}>
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>
              {metric.value == null ? (
                <span className={styles.unavailable}>暂不可用</span>
              ) : (
                <>
                  <strong>{analyticsNumber.format(metric.value)}</strong>
                  <span>{metric.unit}</span>
                </>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <p className={styles.note}>
        访客数按匿名会话标识估算，同一人使用不同设备可能重复计数。下载入口点击不代表文件已下载完成。
      </p>
      {traffic === null ? (
        <Notice>
          <strong>访问数据暂不可用</strong>
          <br />
          统计来源尚未启用或暂时无法连接，恢复后可重新读取。
        </Notice>
      ) : (
        <AnalyticsTrend trend={traffic.trend} />
      )}
    </section>
  );
}

export function AnalyticsDownloads({
  downloads,
}: Pick<Analytics, "downloads">) {
  return (
    <section aria-labelledby="analytics-downloads-title">
      <div className={styles.sectionHeading}>
        <h2 id="analytics-downloads-title" className={styles.sectionTitle}>
          安装包下载
        </h2>
        {downloads !== null && (
          <p className={styles.downloadTotal}>
            累计 <strong>{analyticsNumber.format(downloads.total)}</strong> 次
          </p>
        )}
      </div>
      <p className={styles.note}>
        GitHub 所有来源的累计下载次数，不代表下载人数或安装人数。
      </p>
      {downloads === null ? (
        <Notice>
          <strong>下载数据暂不可用</strong>
          <br />
          暂时无法读取 GitHub 下载计数，请稍后刷新。
        </Notice>
      ) : downloads.versions.length ? (
        <table className={styles.downloadTable}>
          <caption className={styles.visuallyHidden}>
            各版本安装包下载次数
          </caption>
          <thead>
            <tr>
              <th scope="col">版本</th>
              <th scope="col">安装包</th>
              <th scope="col">下载次数</th>
            </tr>
          </thead>
          <tbody>
            {downloads.versions.map((item) => (
              <tr key={`${item.version}:${item.filename}`}>
                <th scope="row">{item.version}</th>
                <td>{item.filename}</td>
                <td>{analyticsNumber.format(item.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={styles.empty}>暂无已公开的正式安装包。</p>
      )}
    </section>
  );
}
