"use client";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Notice } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { type Resource, type Version, statuses } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
const noVersion = "__none__";
export function AdminResources() {
  const query = useQuery({
    queryKey: ["admin-resources"],
    queryFn: () => api<Resource[]>("/admin/resources"),
  });
  return (
    <>
      {query.isPending && <Notice>正在加载资源…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {!query.isPending && !query.error && !query.data?.length && (
        <Notice>目前没有资源。</Notice>
      )}
      {query.data?.map((resource) => (
        <Publication key={resource.id} resource={resource} />
      ))}
    </>
  );
}
function Publication({ resource }: { resource: Resource }) {
  const query = useQuery({
    queryKey: ["versions", resource.id],
    queryFn: () => api<Version[]>(`/resources/${resource.id}/versions`),
  });
  const cache = useQueryClient();
  const [version, setVersion] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  async function act(publish: boolean) {
    setBusy(true);
    try {
      await api(
        `/admin/resources/${resource.id}${publish ? "/publications" : ""}`,
        publish ? "POST" : "PATCH",
        publish
          ? { versionId: version }
          : { status: resource.status === "HIDDEN" ? "ACTIVE" : "HIDDEN" },
      );
      await cache.invalidateQueries({ queryKey: ["admin-resources"] });
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="version-row">
      <h3>{resource.name}</h3>
      <p>
        {statuses[resource.visibility]} · {statuses[resource.status]} ·{" "}
        {resource.license}
      </p>
      <div className="actions">
        <Select
          value={version || noVersion}
          onValueChange={(selected) =>
            setVersion(selected === noVersion ? "" : selected)
          }
        >
          <SelectTrigger
            className="w-full"
            aria-label={`${resource.name}的发布版本`}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem value={noVersion}>选择就绪版本</SelectItem>
            {query.data
              ?.filter((version) => version.validationStatus === "READY")
              .map((version) => (
                <SelectItem value={version.id} key={version.id}>
                  {version.version}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <Button disabled={!version || busy} onClick={() => act(true)}>
          发布公开资源
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => act(false)}>
          {resource.status === "HIDDEN" ? "恢复" : "隐藏"}
        </Button>
      </div>
      {error !== undefined && <Notice error={error} />}{" "}
      {query.error && <Notice error={query.error} />}
    </article>
  );
}
