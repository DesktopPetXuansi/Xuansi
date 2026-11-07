"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type Resource, type Version } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ResourceRow } from "./resources";

// 收藏默认跟随当前版本；内部标识不发送到业务接口。
const currentVersion = "__current_resource_version__";
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
          <Select
            value={pinnedVersionId || currentVersion}
            disabled={busy}
            onValueChange={(value) =>
              void update(value === currentVersion ? "" : value)
            }
          >
            <SelectTrigger aria-label="安装版本" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              <SelectItem value={currentVersion}>使用当前版本</SelectItem>
              {query.data
                ?.filter((version) => version.validationStatus === "READY")
                .map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    {version.version}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </label>
        {busy && <small role="status">正在保存…</small>}
      </div>
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}
    </>
  );
}
