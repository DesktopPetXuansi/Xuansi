import { ResourceEditor } from "@/features/resource-editor";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ResourceEditor id={id} />;
}
