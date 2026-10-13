"use client";
import { useMe } from "@/components/navigation";
import { Heading, Notice } from "@/components/ui";
import { bytes } from "@/lib/types";
import Link from "next/link";
export function Overview() {
  const me = useMe();
  return (
    <>
      <Heading title={`你好，${me.data?.displayName || "朋友"}。`}>
        每个资源都有明确的版本与许可，整理好再带到桌面。
      </Heading>
      <div className="grid-two">
        <section className="panel">
          <p className="eyebrow">STORAGE / 存储空间</p>
          <p className="stat">{bytes(me.data?.storage.usedBytes)}</p>
          <p className="muted">
            总额度 {bytes(me.data?.storage.quotaBytes)} · 上传预留{" "}
            {bytes(me.data?.storage.reservedBytes)}
          </p>
        </section>
        <section className="panel">
          <h3>开始整理你的资源</h3>
          <p className="muted">完整模型包、独立动作、表情和桌面形象。</p>
          <Link className="button-link" href="/dashboard/resources/new">
            创建资源 +
          </Link>
        </section>
      </div>
      {!me.data?.emailVerified && (
        <Notice>
          邮箱尚未验证。
          <Link className="quiet-link" href="/verify-email">
            验证邮箱
          </Link>{" "}
          后可以上传资源。
        </Notice>
      )}
    </>
  );
}
