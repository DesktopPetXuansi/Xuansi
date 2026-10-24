"use client";

import { safeUrl } from "@/lib/api";
import { type Resource, kinds, statuses } from "@/lib/types";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import styles from "./resources.module.css";

function ResourceCover({
  resource,
  personal,
}: {
  resource: Resource;
  personal: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const source = resource.coverUrl ? safeUrl(resource.coverUrl) : "";
  if (!source || source === "#" || failed) {
    return (
      <div
        className={`${styles.previewFallback} ${personal ? "resource-placeholder" : styles.preview}`}
      >
        <span>{failed ? "预览暂时不可用" : "作者暂未提供预览图"}</span>
        {!personal && <small>以资源介绍与客户端试载为准</small>}
      </div>
    );
  }
  return (
    <Image
      unoptimized
      className={personal ? "resource-thumb" : styles.preview}
      src={source}
      alt={`${resource.name}预览`}
      width={personal ? 78 : 360}
      height={personal ? 90 : 300}
      onError={() => {
        setFailed(true);
        console.warn("[资源预览] 封面未能载入");
      }}
    />
  );
}

// 收藏和个人资源继续复用原入口；公开目录将卡片标题放在社区分区的下一级。
export function ResourceRow({
  resource,
  personal = false,
  headingLevel = 2,
}: {
  resource: Resource;
  personal?: boolean;
  headingLevel?: 2 | 3;
}) {
  const Title = headingLevel === 3 ? "h3" : "h2";
  const addon = ["MOTION", "EXPRESSION"].includes(resource.kind);
  return (
    <Link
      href={`${personal ? "/dashboard" : ""}/resources/${resource.id}`}
      className={personal ? "resource-link" : styles.card}
      aria-label={
        personal
          ? `管理资源：${resource.name}`
          : `查看${resource.name}的介绍与使用说明`
      }
    >
      <article className={personal ? "row" : undefined}>
        <ResourceCover
          key={resource.coverUrl ?? "missing"}
          resource={resource}
          personal={personal}
        />
        <div className={personal ? "row-body" : styles.cardBody}>
          {!personal && (
            <span className={styles.kind}>
              {kinds[resource.kind] ?? resource.kind}
            </span>
          )}
          <Title className="resource-title" title={resource.name}>
            {resource.name}
          </Title>
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
          {!personal && (
            <span className={styles.cardAction}>
              {addon ? "查看配套说明" : "查看介绍与使用"}
              <span aria-hidden="true"> ↗</span>
            </span>
          )}
        </div>
      </article>
    </Link>
  );
}
