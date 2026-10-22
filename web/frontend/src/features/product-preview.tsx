"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, useState, type KeyboardEvent } from "react";
import styles from "./product-preview.module.css";

const views = [
  {
    id: "chat",
    label: "开始对话",
    title: "从想说的第一句话开始。",
    description:
      "输入文字，或配置好语音后开启连续对话。看屏幕、朗读和休眠，都有清楚的开关。",
    image: "chat",
    href: "/docs/chat",
    link: "了解聊天设置",
  },
  {
    id: "memory",
    label: "管理记忆",
    title: "留下什么，你看得见。",
    description:
      "在记忆页查看、编辑和保存长期记忆。使用在线 AI 读取这些内容，需要你另行授权。",
    image: "memory",
    href: "/privacy",
    link: "了解记忆与隐私",
  },
  {
    id: "appearance",
    label: "更换形象",
    title: "陪伴的样子，也由你来选。",
    description:
      "使用自带的玄司，或导入图片、动图与 Live2D。选中喜欢的形象，点击使用。",
    image: "appearance",
    href: "/docs/appearance",
    link: "查看换形象步骤",
  },
] as const;

// 图片来自隔离的 v0.8.0 原生客户端；只在点击时切换，不自动轮播。
export function ProductPreview() {
  const [selected, setSelected] = useState(2);
  const [imageFailed, setImageFailed] = useState(false);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const view = views[selected];

  function selectView(index: number) {
    setSelected(index);
    setImageFailed(false);
    console.debug("[客户端实拍] 切换到", views[index].label);
  }

  function moveTab(event: KeyboardEvent<HTMLDivElement>) {
    const next =
      event.key === "ArrowRight"
        ? (selected + 1) % views.length
        : event.key === "ArrowLeft"
          ? (selected + views.length - 1) % views.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? views.length - 1
              : undefined;
    if (next === undefined) return;
    event.preventDefault();
    selectView(next);
    tabs.current[next]?.focus();
  }

  return (
    <section
      id="product-preview"
      className={styles.section}
      aria-labelledby="preview-title"
    >
      <header className={styles.heading}>
        <div>
          <p className="eyebrow">看见真实的玄司</p>
          <h2 id="preview-title">看看玄司，用起来是什么样。</h2>
        </div>
        <p>
          从对话到记忆，再到换个样子。
          <br />
          这是客户端实际运行的界面。
        </p>
      </header>
      <div
        className={styles.tabs}
        role="tablist"
        aria-label="查看客户端界面"
        onKeyDown={moveTab}
      >
        {views.map((item, index) => (
          <button
            key={item.id}
            ref={(element) => {
              tabs.current[index] = element;
            }}
            id={`preview-tab-${item.id}`}
            role="tab"
            type="button"
            aria-controls="preview-panel"
            aria-selected={selected === index}
            tabIndex={selected === index ? 0 : -1}
            onClick={() => selectView(index)}
          >
            <span aria-hidden>0{index + 1}</span>
            {item.label}
          </button>
        ))}
      </div>
      <div
        id="preview-panel"
        role="tabpanel"
        aria-labelledby={`preview-tab-${view.id}`}
        tabIndex={0}
        className={styles.panel}
      >
        <div className={styles.copy}>
          <p className={styles.version}>WINDOWS · v0.8.0</p>
          <h3>{view.title}</h3>
          <p>{view.description}</p>
          <Link className="quiet-link" href={view.href}>
            {view.link} →
          </Link>
        </div>
        <figure className={styles.figure}>
          <a
            href={`/product/client-${view.image}-v0.8.0.webp`}
            target="_blank"
            rel="noreferrer"
            aria-label={`查看${view.label}界面原图（新窗口）`}
          >
            {imageFailed ? (
              <div className={styles.unavailable} role="status">
                截图暂时无法显示。点击这里打开原图，或切换其他界面。
              </div>
            ) : (
              <Image
                key={view.id}
                src={`/product/client-${view.image}-v0.8.0.webp`}
                alt={`玄司 0.8.0 客户端${view.label}页面，示例数据`}
                width={880}
                height={660}
                onError={() => {
                  setImageFailed(true);
                  console.warn("[客户端实拍] 截图加载失败");
                }}
                sizes="(max-width: 640px) calc(100vw - 40px), (max-width: 900px) calc(100vw - 64px), 760px"
              />
            )}
          </a>
          <figcaption>v0.8.0 客户端实拍 · 点击查看原图</figcaption>
        </figure>
      </div>
      <p className={styles.note}>
        草稿和记忆为演示用示例数据，未连接 AI 服务。
      </p>
    </section>
  );
}
