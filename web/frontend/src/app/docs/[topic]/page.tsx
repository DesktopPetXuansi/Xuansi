import { HelpArticle } from "@/features/help";
import { findHelpTopic, helpTopics } from "@/features/help/content";
import { notFound } from "next/navigation";
import { publicPageMetadata } from "@/lib/site-metadata";

// 指南路径是固定公开内容，构建时生成；未知主题保留正常 404。
export const dynamicParams = false;
export function generateStaticParams() {
  return helpTopics.map((topic) => ({ topic: topic.slug }));
}
export async function generateMetadata({
  params,
}: {
  params: Promise<{ topic: string }>;
}) {
  const topic = findHelpTopic((await params).topic);
  if (!topic) notFound();
  return publicPageMetadata(topic.title, topic.summary, `/docs/${topic.slug}`);
}
export default async function Page({
  params,
}: {
  params: Promise<{ topic: string }>;
}) {
  const topic = findHelpTopic((await params).topic);
  if (!topic) notFound();
  return <HelpArticle topic={topic} />;
}
