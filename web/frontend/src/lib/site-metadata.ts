import type { Metadata } from "next";

// 公开页面各自声明 canonical，避免账号与授权页面继承首页地址。
export function publicPageMetadata(
  title: string,
  description: string,
  path: string,
) {
  const shareTitle = `${title} · 玄司 Xuansi`;
  const images = [
    {
      url: "/brand/share.png",
      width: 1200,
      height: 630,
      alt: "玄司 Xuansi · 把陪伴，留在你的桌面。",
    },
  ];
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      locale: "zh_CN",
      siteName: "玄司 Xuansi",
      title: shareTitle,
      description,
      url: path,
      images,
    },
    twitter: {
      card: "summary_large_image",
      title: shareTitle,
      description,
      images,
    },
  } satisfies Metadata;
}
