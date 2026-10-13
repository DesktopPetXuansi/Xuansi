"use client";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Resource, type Version } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ResourceRow } from "./resources";
export function LibraryItem({
  resource,
  pinnedVersionId,
}: {
  resource: Resource;
  pinnedVersionId: string | null;
}) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["versions", resource.id],
    queryFn: () => api<Version[]>(`/resources/${resource.id}/versions`),
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  async function update(value: string) {
    setBusy(true);
    setError(undefined);
    try {
      await api(`/me/library/${resource.id}`, "PUT", {
        pinnedVersionId: value || null,
      });
      await cache.invalidateQueries({ queryKey: ["library"] });
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <ResourceRow resource={resource} />
      <div className="actions">
        <label>
          安装版本{" "}
          <select
            value={pinnedVersionId ?? ""}
            disabled={busy}
            onChange={(event) => update(event.target.value)}
          >
            <option value="">使用当前版本</option>
            {query.data
              ?.filter((version) => version.validationStatus === "READY")
              .map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version}
                </option>
              ))}
          </select>
        </label>
        {busy && <small role="status">正在保存…</small>}
      </div>
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}
    </>
  );
}
