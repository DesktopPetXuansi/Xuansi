"use client";
import { useMe } from "@/components/navigation";
import { Button, Heading, Notice } from "@/components/ui";
import { api, safeUrl } from "@/lib/api";
import { type Resource, kinds } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { authHref } from "./identity/return-path";
import { VersionList } from "./version-list";
import styles from "./resources.module.css";

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
  if (resource.error) {
    return (
      <>
        <Notice error={resource.error} />
        <div className="actions">
          <Button className="secondary" onClick={() => void resource.refetch()}>
            重新加载
          </Button>
          <Link className="quiet-link" href="/resources">
            返回挑选形象 →
          </Link>
        </div>
      </>
    );
  }
  if (!resource.data) return null;
  const item = resource.data;
  const supplement = ["MOTION", "EXPRESSION"].includes(item.kind);
  return (
    <>
      <Link className="quiet-link" href="/resources">
        ← 返回挑选形象
      </Link>
      <Heading eyebrow={kinds[item.kind]} title={item.name}>
        {item.description || "作者尚未添加介绍。"}
      </Heading>
      <div className="split">
        <section>
          {item.coverUrl && (
            <Image
              unoptimized
              className={styles.detailImage}
              src={safeUrl(item.coverUrl)}
              alt={`${item.name}预览`}
              width={720}
              height={300}
            />
          )}
          <h2>下载到电脑</h2>
          <p>
            {item.visibility === "PUBLIC"
              ? "公开资源无需登录即可下载。下载后还需要在客户端本地导入，再点击“使用这个形象”。"
              : "私有资源仅对有权限且已验证邮箱的账号开放下载。"}
          </p>
          <VersionList id={id} />
          <section className={styles.instructions}>
            <h2>下载后怎么用？</h2>
            {supplement ? (
              <p>
                这是给已有 Live2D 形象使用的
                {item.kind === "MOTION" ? "动作" : "表情"}
                ，不能单独当作桌宠形象。请核对下方版本依赖，与对应的模型配套使用。
              </p>
            ) : (
              <ol>
                <li>把下载的资源包解压到一个固定文件夹。</li>
                <li>
                  在客户端打开“更换形象” → “本地导入”，选择图片、动图或导出的
                  .model3.json 文件。
                </li>
                <li>预览通过后，点击“使用这个形象”。</li>
              </ol>
            )}
            <p>
              网页下载不会直接切换桌面上的形象。请先遵守作者许可；Live2D
              需要在客户端实际试载。
            </p>
            <div className="actions">
              <Link className="quiet-link" href="/docs/appearance">
                查看详细使用步骤 →
              </Link>
              <Link className="quiet-link" href="/docs/troubleshooting">
                导入有问题？
              </Link>
            </div>
          </section>
        </section>
        <aside className="panel">
          <h2>作者与使用许可</h2>
          <p>作者：{item.author || "未填写"}</p>
          <p>许可：{item.license || "未声明，请先联系作者确认使用范围"}</p>
          {item.source && (
            <p>
              <a
                className="quiet-link"
                href={safeUrl(item.source)}
                rel="noreferrer"
                target="_blank"
              >
                查看原始来源 ↗
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
            收藏方便以后找到这个资源，不会自动下载或更换形象。
          </p>
          {me.isPending ? (
            <Notice>正在确认登录状态…</Notice>
          ) : me.error ? (
            <>
              <Notice error={me.error} />
              <Button className="secondary" onClick={() => void me.refetch()}>
                重试登录状态
              </Button>
            </>
          ) : me.data ? (
            <Button
              disabled={add.isPending || add.isSuccess}
              onClick={() => add.mutate()}
            >
              {add.isSuccess ? "已收藏" : "收藏这个资源"}
            </Button>
          ) : (
            <Link
              className="button-link"
              href={authHref("/login", `/resources/${id}`)}
            >
              登录后收藏
            </Link>
          )}
          {add.error && <Notice error={add.error} />}
        </aside>
      </div>
    </>
  );
}
