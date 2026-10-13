import { ResourceDetail } from "@/features/resources";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="container">
      <ResourceDetail id={id} />
    </div>
  );
}
